"""Reliability-gate CLI entry point (spec §12.2 point 3, §14.9 v1.8).

Drives the soak/ runner end-to-end. Typical invocations:

    # Production soak (48 hours — v1.8 calibration):
    uv run scripts/run_soak_test.py --duration-days 2 --cadence-s 60

    # Short diagnostic (10 minutes, samples every 30 s):
    uv run scripts/run_soak_test.py --duration-days 0 \\
        --duration-extra-s 600 --cadence-s 1 --sample-interval-s 30

    # Resume from checkpoint:
    uv run scripts/run_soak_test.py --resume

Output:
  - Status line every sample interval: elapsed / target / RSS / FDs / decisions.
  - DuckDB file at --db (default data/duckdb/soak.duckdb) accumulates
    forecasts, decisions, soak_resource_samples, soak_incidents for
    post-hoc analysis.
  - On success (reached duration, no incidents): exit 0.
  - On incident: exit non-zero with the incident class on stderr.
  - On KeyboardInterrupt: save state + exit 130 (conventional).

The runner is idempotent with --resume: re-running after an interrupt
picks up at the last checkpoint without losing progress.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reliability-gate soak-test runner (§12.2 point 3)",
    )
    parser.add_argument(
        "--duration-days",
        type=float,
        default=2.0,
        help="Wall-clock soak duration in days (default: 2 per spec v1.8).",
    )
    parser.add_argument(
        "--duration-extra-s",
        type=float,
        default=0.0,
        help="Additional duration in seconds on top of --duration-days.",
    )
    parser.add_argument(
        "--cadence-s",
        type=float,
        default=60.0,
        help="Wall-clock seconds between sim-day ticks (default: 60 ⇒ 1 sim-day per real minute).",
    )
    parser.add_argument(
        "--sample-interval-s",
        type=float,
        default=60.0,
        help="Wall-clock seconds between resource samples (default: 60).",
    )
    parser.add_argument(
        "--checkpoint-interval-s",
        type=float,
        default=600.0,
        help="Wall-clock seconds between checkpoint writes (default: 600).",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("data/duckdb/soak.duckdb"),
        help="DuckDB file for soak telemetry (default: data/duckdb/soak.duckdb).",
    )
    parser.add_argument(
        "--checkpoint-path",
        type=Path,
        default=Path("data/soak/checkpoint.pkl"),
        help="Checkpoint file path (default: data/soak/checkpoint.pkl).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the last checkpoint if it exists.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed for the synthetic LatentPath (default: 0).",
    )
    parser.add_argument(
        "--n-sim-days",
        type=int,
        default=3_000,
        help="Length of the underlying LatentPath in sim-days (default: 3_000 — "
        "enough for ~48 hours at 1 sim-day/min with headroom).",
    )
    return parser.parse_args(argv)


def _build_pipeline(args: argparse.Namespace):
    """Wire up the real pipeline components the runner ticks through."""
    from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
    from controller import Controller, seed_cold_start
    from desks.regime_classifier import GroundTruthRegimeClassifier
    from persistence import connect, init_db
    from sim.latent_state import LatentMarket
    from sim.observations import ObservationChannels
    from sim.regimes import REGIMES
    from soak import SoakRunner, SyntheticDataFeed

    args.db.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(args.db)
    init_db(conn)

    path = LatentMarket(n_days=args.n_sim_days, seed=args.seed).generate()
    channels = ObservationChannels.build(path, mode="clean", seed=args.seed)

    # Cold-start the controller with uniform weights on all 4 regimes.
    boot_ts = datetime.now(tz=UTC)
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
        boot_ts=boot_ts,
        default_cold_start_limit=1.0e9,
    )
    controller = Controller(conn=conn)
    classifier = GroundTruthRegimeClassifier()

    feed = SyntheticDataFeed(
        channels=channels,
        controller=controller,
        classifier=classifier,
    )

    def _status(info: dict[str, float]) -> None:
        pct = 100.0 * info["elapsed_s"] / max(info["target_s"], 1.0)
        print(
            f"[soak] elapsed={info['elapsed_s']:.0f}s/"
            f"{info['target_s']:.0f}s ({pct:.1f}%) "
            f"RSS={info['rss_mb']:.1f}MB "
            f"FDs={info['open_fds']:.0f} "
            f"decisions={info['n_decisions']:.0f}",
            file=sys.stderr,
            flush=True,
        )

    duration_s = args.duration_days * 86_400.0 + args.duration_extra_s
    runner = SoakRunner(
        conn=conn,
        db_path=args.db,
        checkpoint_path=args.checkpoint_path,
        tick_fn=feed.tick,
        duration_seconds=duration_s,
        cadence_seconds=args.cadence_s,
        sample_interval_seconds=args.sample_interval_s,
        checkpoint_interval_seconds=args.checkpoint_interval_s,
        seed=args.seed,
        resume=args.resume,
        status_callback=_status,
    )
    return runner, conn


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    runner, conn = _build_pipeline(args)
    try:
        result = runner.run()
    except KeyboardInterrupt:
        print("\n[soak] interrupted — state saved", file=sys.stderr)
        return 130
    finally:
        conn.close()

    if result.completed:
        print(
            f"[soak] PASSED: elapsed={result.wall_clock_elapsed_s:.0f}s, "
            f"decisions={result.final_state.n_decisions_emitted}, "
            f"samples={result.n_samples}",
            file=sys.stderr,
        )
        return 0

    assert result.incident is not None
    print(
        f"[soak] FAILED: incident={result.incident.incident_class} detail={result.incident.detail}",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
