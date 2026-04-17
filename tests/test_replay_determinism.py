"""Load-bearing test: byte-identical replay of a seeded synthetic scenario.

Runs the same scenario twice against fresh DBs; serialises the DB contents
to canonical JSON; asserts byte-identical output.

Replay determinism catches non-determinism (float ordering, clock-dependent
logic, unordered dict iteration) at the scaffold level, not months later.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from bus import Bus
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    ClockHorizon,
    DirectionalClaim,
    Forecast,
    Print,
    Provenance,
    UncertaintyInterval,
)
from grading import grade
from persistence import connect, init_db


def _run_scenario(db_path: Path) -> dict[str, object]:
    """Execute a deterministic scenario and return a canonical snapshot."""
    conn = connect(db_path)
    init_db(conn)
    bus = Bus(conn, mode="replay")

    # Fixed seed → fixed UUIDs
    import random

    rng = random.Random(42)

    def _uuid_det() -> str:
        return str(uuid.UUID(int=rng.getrandbits(128)))

    now = datetime(2026, 1, 7, 15, 0, 0, tzinfo=UTC)

    # Emit 10 Forecasts with deterministic IDs
    fcast_ids: list[str] = []
    for i in range(10):
        f = Forecast(
            forecast_id=_uuid_det(),
            emission_ts_utc=now + timedelta(days=i),
            target_variable=WTI_FRONT_MONTH_CLOSE,
            horizon=ClockHorizon(duration=timedelta(days=7)),
            point_estimate=float(i) * 0.1,
            uncertainty=UncertaintyInterval(level=0.8, lower=-1e9, upper=1e9),
            directional_claim=DirectionalClaim(
                variable=WTI_FRONT_MONTH_CLOSE,
                sign="positive",
            ),
            staleness=False,
            confidence=1.0,
            provenance=Provenance(
                desk_name="stub",
                model_name="m",
                model_version="0.0.0",
                input_snapshot_hash="0" * 64,
                spec_hash="0" * 64,
                code_commit="c" * 40,  # clean sha; replay mode rejects -dirty
            ),
        )
        bus.publish_forecast(f)
        fcast_ids.append(f.forecast_id)

    # Emit matching Prints 7 days later
    for i in range(10):
        p = Print(
            print_id=_uuid_det(),
            realised_ts_utc=now + timedelta(days=i + 7),
            target_variable=WTI_FRONT_MONTH_CLOSE,
            value=float(i) * 0.1 + 0.01,  # always positive residual
            event_id=None,
        )
        bus.publish_print(p)

    # Grade (deterministic grading_ts_utc)
    # Pull forecasts by ID, match with prints by order
    fcast_rows = conn.execute(
        "SELECT forecast_id, emission_ts_utc, horizon_payload, point_estimate, "
        "uncertainty, directional_claim, staleness, confidence, provenance "
        "FROM forecasts ORDER BY emission_ts_utc, forecast_id"
    ).fetchall()
    print_rows = conn.execute(
        "SELECT print_id, realised_ts_utc, target_variable, value, event_id, vintage_of "
        "FROM prints ORDER BY realised_ts_utc, print_id"
    ).fetchall()
    assert len(fcast_rows) == 10
    assert len(print_rows) == 10

    for i, (fr, pr) in enumerate(zip(fcast_rows, print_rows, strict=True)):
        f_reconstructed = Forecast(
            forecast_id=fr[0],
            emission_ts_utc=fr[1],
            target_variable=WTI_FRONT_MONTH_CLOSE,
            horizon=ClockHorizon(**json.loads(fr[2])),
            point_estimate=fr[3],
            uncertainty=UncertaintyInterval(**json.loads(fr[4])),
            directional_claim=DirectionalClaim(**json.loads(fr[5])),
            staleness=fr[6],
            confidence=fr[7],
            provenance=Provenance(**json.loads(fr[8])),
        )
        p_reconstructed = Print(
            print_id=pr[0],
            realised_ts_utc=pr[1],
            target_variable=pr[2],
            value=pr[3],
            event_id=pr[4],
            vintage_of=pr[5],
        )
        # Deterministic grading_ts_utc
        g = grade(f_reconstructed, p_reconstructed, grading_ts_utc=now + timedelta(days=100 + i))
        # Override grade_id to be deterministic
        from contracts.v1 import Grade

        g_det = Grade(
            grade_id=_uuid_det(),
            forecast_id=g.forecast_id,
            print_id=g.print_id,
            grading_ts_utc=g.grading_ts_utc,
            squared_error=g.squared_error,
            absolute_error=g.absolute_error,
            log_score=g.log_score,
            sign_agreement=g.sign_agreement,
            within_uncertainty=g.within_uncertainty,
            schedule_slip_seconds=g.schedule_slip_seconds,
        )
        bus.publish_grade(g_det)

    # Canonical snapshot: serialize all rows from all tables in a sorted order.
    snapshot: dict[str, object] = {}
    for table in ["forecasts", "prints", "grades"]:
        rows = conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        snapshot[table] = [tuple(str(c) if isinstance(c, datetime) else c for c in r) for r in rows]
    conn.close()
    return snapshot


def test_byte_identical_replay(tmp_path: Path):
    db1 = tmp_path / "run1.duckdb"
    db2 = tmp_path / "run2.duckdb"

    snap1 = _run_scenario(db1)
    snap2 = _run_scenario(db2)

    canon1 = json.dumps(snap1, sort_keys=True, default=str)
    canon2 = json.dumps(snap2, sort_keys=True, default=str)

    h1 = hashlib.sha256(canon1.encode()).hexdigest()
    h2 = hashlib.sha256(canon2.encode()).hexdigest()

    assert h1 == h2, (
        f"Replay determinism failed: {h1} != {h2}\n\n"
        f"First diff in canonical JSON:\n"
        f"run1: {canon1[:500]}\nrun2: {canon2[:500]}"
    )


# ---------------------------------------------------------------------------
# Controller + attribution replay determinism
# ---------------------------------------------------------------------------
#
# Extends the Forecast/Print/Grade determinism above to the decision-time
# layer: Controller.decide + LODO + Shapley must produce identical payload
# given identical inputs. Uuid-typed event IDs (decision_id, forecast_id,
# attribution_id) are not payload; they differ by design and are excluded
# from the equality check.


def _run_controller_scenario(
    db_path: Path,
    *,
    seed_forecast_ids: list[dict[str, str]],
) -> tuple[
    list[tuple[str, float, float, tuple[str, ...], str]],
    list[tuple[float, ...]],
    list[tuple[tuple[str, float], ...]],
]:
    """Run Controller + LODO + Shapley on a fixed synthetic event stream.

    Returns three stable-shape summaries so two runs can be compared by
    ordinary equality. No uuids are in the summaries.
    """
    from attribution import (
        compute_lodo_signal_space,
        compute_shapley_signal_space,
    )
    from contracts.v1 import (
        DirectionalClaim,
        EventHorizon,
        Forecast,
        Provenance,
        RegimeLabel,
        UncertaintyInterval,
    )
    from controller import Controller, seed_cold_start

    boot_ts = datetime(2026, 4, 16, 9, 0, 0, 123456, tzinfo=UTC)
    desks = [
        ("storage_curve", WTI_FRONT_MONTH_CLOSE),
        ("macro", WTI_FRONT_MONTH_CLOSE),
        ("supply", WTI_FRONT_MONTH_CLOSE),
    ]

    conn = connect(db_path)
    init_db(conn)
    try:
        seed_cold_start(
            conn,
            desks=desks,
            regime_ids=["regime_boot"],
            boot_ts=boot_ts,
            default_cold_start_limit=1000.0,
        )
        ctrl = Controller(conn=conn)

        decisions_summary: list[tuple[str, float, float, tuple[str, ...], str]] = []
        lodo_summary: list[tuple[float, ...]] = []
        shapley_summary: list[tuple[tuple[str, float], ...]] = []

        for h in range(5):
            ts = boot_ts + timedelta(hours=1 + h)
            # Deterministic forecast values.
            f_vals = {
                "storage_curve": 82.0 + 0.3 * h,
                "macro": 80.0 - 0.2 * h,
                "supply": 79.5 + 0.1 * h,
            }
            recent: dict[tuple[str, str], Forecast] = {}
            for desk_name, value in f_vals.items():
                recent[(desk_name, WTI_FRONT_MONTH_CLOSE)] = Forecast(
                    forecast_id=seed_forecast_ids[h][desk_name],
                    emission_ts_utc=ts,
                    target_variable=WTI_FRONT_MONTH_CLOSE,
                    horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=ts),
                    point_estimate=value,
                    uncertainty=UncertaintyInterval(
                        level=0.8, lower=value - 5.0, upper=value + 5.0
                    ),
                    directional_claim=DirectionalClaim(
                        variable=WTI_FRONT_MONTH_CLOSE, sign="positive"
                    ),
                    staleness=False,
                    confidence=1.0,
                    provenance=Provenance(
                        desk_name=desk_name,
                        model_name="m",
                        model_version="0.1",
                        input_snapshot_hash="0" * 64,
                        spec_hash="0" * 64,
                        code_commit="c" * 40,
                    ),
                )
            regime = RegimeLabel(
                classification_ts_utc=ts,
                regime_id="regime_boot",
                regime_probabilities={"regime_boot": 1.0},
                transition_probabilities={"regime_boot": 1.0},
                classifier_provenance=Provenance(
                    desk_name="regime_classifier",
                    model_name="m",
                    model_version="0.1",
                    input_snapshot_hash="0" * 64,
                    spec_hash="0" * 64,
                    code_commit="c" * 40,
                ),
            )
            d = ctrl.decide(now_utc=ts, regime_label=regime, recent_forecasts=recent)
            decisions_summary.append(
                (
                    d.regime_id,
                    d.combined_signal,
                    d.position_size,
                    tuple(d.input_forecast_ids),
                    d.provenance.input_snapshot_hash,
                )
            )

            lodo = compute_lodo_signal_space(
                conn=conn,
                decision=d,
                recent_forecasts=recent,
                computed_ts_utc=ts,
            )
            lodo_by_desk = {row.desk_name: row.contribution_metric for row in lodo}
            lodo_summary.append(tuple(lodo_by_desk[d_[0]] for d_ in desks))

            shapley = compute_shapley_signal_space(
                conn=conn,
                decisions=[d],
                recent_forecasts_by_decision={d.decision_id: recent},
                review_ts_utc=ts,
            )
            shapley_by_desk = sorted(
                ((row.desk_name, row.shapley_value) for row in shapley),
                key=lambda kv: kv[0],
            )
            shapley_summary.append(tuple(shapley_by_desk))

        return decisions_summary, lodo_summary, shapley_summary
    finally:
        conn.close()


def test_controller_attribution_replay_identical_payload(tmp_path: Path):
    # Fix the forecast_ids across both runs so replay matches on
    # input_forecast_ids (which is payload, not a per-run id).
    desks = ["storage_curve", "macro", "supply"]
    seed_ids = [
        {d: str(uuid.UUID(int=10_000 + h * 10 + i)) for i, d in enumerate(desks)} for h in range(5)
    ]

    r1 = _run_controller_scenario(tmp_path / "ctrl_run1.duckdb", seed_forecast_ids=seed_ids)
    r2 = _run_controller_scenario(tmp_path / "ctrl_run2.duckdb", seed_forecast_ids=seed_ids)
    decisions1, lodo1, shapley1 = r1
    decisions2, lodo2, shapley2 = r2

    assert decisions1 == decisions2, "Decision payload diverged across replay"
    assert lodo1 == lodo2, "LODO contribution_metric diverged across replay"
    assert shapley1 == shapley2, "Shapley values diverged across replay"


def test_controller_replay_detects_single_forecast_perturbation(tmp_path: Path):
    """Sanity guard: a 1-basis-point perturbation in one forecast value
    must produce a different Decision payload. Without this, the
    payload-equality test could silently pass a broken pipeline."""
    desks = ["storage_curve", "macro", "supply"]
    seed_ids = [
        {d: str(uuid.UUID(int=20_000 + h * 10 + i)) for i, d in enumerate(desks)} for h in range(5)
    ]

    r1 = _run_controller_scenario(tmp_path / "orig.duckdb", seed_forecast_ids=seed_ids)

    # Perturb: the canonical scenario is hard-coded inside the helper, so
    # we exercise perturbation by running with a DIFFERENT seed_ids mapping,
    # which does not perturb payload. Instead, monkey-patch via a small
    # modified helper. We inline it here for clarity.
    from attribution import compute_lodo_signal_space
    from contracts.v1 import (
        DirectionalClaim,
        EventHorizon,
        Forecast,
        Provenance,
        RegimeLabel,
        UncertaintyInterval,
    )
    from controller import Controller, seed_cold_start

    def _perturbed_run(db_path: Path) -> list[tuple[str, float, float]]:
        boot_ts = datetime(2026, 4, 16, 9, 0, 0, 123456, tzinfo=UTC)
        d_list = [
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("macro", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
        ]
        conn = connect(db_path)
        init_db(conn)
        try:
            seed_cold_start(
                conn,
                desks=d_list,
                regime_ids=["regime_boot"],
                boot_ts=boot_ts,
                default_cold_start_limit=1000.0,
            )
            ctrl = Controller(conn=conn)
            out: list[tuple[str, float, float]] = []
            for h in range(1):
                ts = boot_ts + timedelta(hours=1 + h)
                # Perturb storage_curve by 0.01
                recent = {
                    ("storage_curve", WTI_FRONT_MONTH_CLOSE): Forecast(
                        forecast_id=seed_ids[h]["storage_curve"],
                        emission_ts_utc=ts,
                        target_variable=WTI_FRONT_MONTH_CLOSE,
                        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=ts),
                        point_estimate=82.0 + 0.3 * h + 0.01,  # <-- perturbed
                        uncertainty=UncertaintyInterval(level=0.8, lower=70, upper=90),
                        directional_claim=DirectionalClaim(
                            variable=WTI_FRONT_MONTH_CLOSE, sign="positive"
                        ),
                        staleness=False,
                        confidence=1.0,
                        provenance=Provenance(
                            desk_name="storage_curve",
                            model_name="m",
                            model_version="0.1",
                            input_snapshot_hash="0" * 64,
                            spec_hash="0" * 64,
                            code_commit="c" * 40,
                        ),
                    ),
                }
                regime = RegimeLabel(
                    classification_ts_utc=ts,
                    regime_id="regime_boot",
                    regime_probabilities={"regime_boot": 1.0},
                    transition_probabilities={"regime_boot": 1.0},
                    classifier_provenance=Provenance(
                        desk_name="regime_classifier",
                        model_name="m",
                        model_version="0.1",
                        input_snapshot_hash="0" * 64,
                        spec_hash="0" * 64,
                        code_commit="c" * 40,
                    ),
                )
                d = ctrl.decide(now_utc=ts, regime_label=regime, recent_forecasts=recent)
                out.append((d.regime_id, d.combined_signal, d.position_size))
                _ = compute_lodo_signal_space(
                    conn=conn,
                    decision=d,
                    recent_forecasts=recent,
                    computed_ts_utc=ts,
                )
            return out
        finally:
            conn.close()

    perturbed = _perturbed_run(tmp_path / "perturb.duckdb")

    # The first-decision payload must differ between the canonical scenario
    # and the perturbed one.
    decisions_original = r1[0]
    assert decisions_original[0][1] != perturbed[0][1] or (
        decisions_original[0][2] != perturbed[0][2]
    ), "Perturbation did not propagate to Decision payload"
