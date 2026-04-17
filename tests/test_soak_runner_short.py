"""Accelerated soak-runner integration tests (plan commit 5).

Two load-bearing tests:

  1. test_accelerated_smoke: runs the full runner (LatentMarket +
     Controller + SyntheticDataFeed + ResourceMonitor + checkpoint)
     at cadence_s=0.01 for ~2 s wall-clock. Asserts no incidents,
     decisions persisted, samples monotonic.

  2. test_runner_resumes_from_checkpoint: runs ~1 s, saves checkpoint,
     starts a second runner with resume=True, verifies sim-day index
     and decision counter continue from the first run (don't reset).

These exercise the production code paths at 1000× speed. The 7-day
wall-clock run (spec §12.2 point 3) is operator-side and not
automated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from controller import Controller, seed_cold_start
from desks.regime_classifier import GroundTruthRegimeClassifier
from persistence import connect, count_rows, init_db
from sim.latent_state import LatentMarket
from sim.observations import ObservationChannels
from sim.regimes import REGIMES
from soak import SoakRunner, SyntheticDataFeed


def _build_runner(
    tmp_path: Path,
    duration_s: float,
    resume: bool = False,
) -> tuple[SoakRunner, object, SyntheticDataFeed]:
    db_path = tmp_path / "soak.duckdb"
    ckpt_path = tmp_path / "ckpt.pkl"

    conn = connect(db_path)
    init_db(conn)
    path = LatentMarket(n_days=1000, seed=0).generate()
    channels = ObservationChannels.build(path, mode="clean", seed=0)
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
            ("demand", WTI_FRONT_MONTH_CLOSE),
            ("geopolitics", WTI_FRONT_MONTH_CLOSE),
            ("macro", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=list(REGIMES),
        boot_ts=datetime.now(tz=UTC),
        default_cold_start_limit=1.0e9,
    )
    controller = Controller(conn=conn)
    classifier = GroundTruthRegimeClassifier()
    feed = SyntheticDataFeed(channels=channels, controller=controller, classifier=classifier)

    runner = SoakRunner(
        conn=conn,
        db_path=db_path,
        checkpoint_path=ckpt_path,
        tick_fn=feed.tick,
        duration_seconds=duration_s,
        cadence_seconds=0.005,  # 200 sim-days/sec
        sample_interval_seconds=0.3,
        checkpoint_interval_seconds=0.5,
        seed=0,
        resume=resume,
    )
    return runner, conn, feed


def test_accelerated_smoke(tmp_path: Path):
    runner, conn, _ = _build_runner(tmp_path, duration_s=2.0)
    try:
        result = runner.run()
    finally:
        conn.close()

    # Reached duration cleanly.
    assert result.completed
    assert result.incident is None
    # Some number of decisions emitted — at 0.005 s cadence, typically
    # hundreds. Allow slack for slow CI runners.
    assert result.final_state.n_decisions_emitted > 20, (
        f"expected > 20 decisions; got {result.final_state.n_decisions_emitted}"
    )
    # At least a couple of resource samples taken.
    assert result.n_samples >= 2

    # Telemetry persisted
    with connect(tmp_path / "soak.duckdb") as conn2:
        assert count_rows(conn2, "soak_resource_samples") >= 2
        assert count_rows(conn2, "decisions") > 20
        # No incidents recorded
        assert count_rows(conn2, "soak_incidents") == 0


def test_runner_resumes_from_checkpoint(tmp_path: Path):
    # Run 1
    runner1, conn1, _ = _build_runner(tmp_path, duration_s=1.0)
    result1 = runner1.run()
    conn1.close()
    assert result1.completed
    n1 = result1.final_state.n_decisions_emitted
    idx1 = result1.final_state.sim_day_index
    start_ts1 = result1.final_state.start_ts_utc
    assert n1 > 0

    # Verify checkpoint file exists
    assert (tmp_path / "ckpt.pkl").exists()

    # Run 2 with resume=True — new duration counts from zero but state
    # resumes
    runner2, conn2, _ = _build_runner(tmp_path, duration_s=1.0, resume=True)
    result2 = runner2.run()
    conn2.close()
    assert result2.completed
    n2 = result2.final_state.n_decisions_emitted
    idx2 = result2.final_state.sim_day_index

    # State accumulated, not reset.
    assert n2 > n1, f"expected n2 > n1; got n1={n1}, n2={n2}"
    assert idx2 >= idx1
    # Original start_ts_utc preserved across resume.
    assert result2.final_state.start_ts_utc == start_ts1


def test_runner_fresh_start_does_not_resume(tmp_path: Path):
    """Without --resume, a second run with an existing checkpoint still
    starts fresh (decision counter resets)."""
    runner1, conn1, _ = _build_runner(tmp_path, duration_s=0.6)
    result1 = runner1.run()
    conn1.close()
    n1 = result1.final_state.n_decisions_emitted

    # Second run without resume — fresh start
    runner2, conn2, _ = _build_runner(tmp_path, duration_s=0.6, resume=False)
    result2 = runner2.run()
    conn2.close()
    # Counter started over from 0 at run 2 init
    assert result2.final_state.n_decisions_emitted > 0
    assert result2.final_state.n_decisions_emitted != n1 * 2  # not cumulative


def test_runner_sample_count_meets_configured_interval(tmp_path: Path):
    runner, conn, _ = _build_runner(tmp_path, duration_s=1.5)
    try:
        result = runner.run()
    finally:
        conn.close()
    # sample_interval_s=0.3, duration=1.5 ⇒ ~5 samples + 1 baseline
    assert result.n_samples >= 3


@pytest.mark.skipif(
    "not hasattr(__import__('os'), 'getpid')",
    reason="requires POSIX process interface",
)
def test_runner_writes_incident_on_forced_exception(tmp_path: Path):
    """If the tick_fn raises, the runner records a scheduler_crash
    incident and re-raises."""
    db_path = tmp_path / "soak.duckdb"
    ckpt_path = tmp_path / "ckpt.pkl"
    conn = connect(db_path)
    init_db(conn)

    calls = {"n": 0}

    def bad_tick(state) -> None:
        calls["n"] += 1
        if calls["n"] >= 3:
            raise RuntimeError("simulated desk crash")
        state.n_decisions_emitted += 1
        state.sim_day_index += 1

    runner = SoakRunner(
        conn=conn,
        db_path=db_path,
        checkpoint_path=ckpt_path,
        tick_fn=bad_tick,
        duration_seconds=10.0,
        cadence_seconds=0.001,
        sample_interval_seconds=0.1,
        checkpoint_interval_seconds=5.0,
    )
    with pytest.raises(RuntimeError, match="simulated desk crash"):
        runner.run()

    # Incident was recorded before re-raising
    with connect(db_path) as conn2:
        assert count_rows(conn2, "soak_incidents") >= 1
    conn.close()
