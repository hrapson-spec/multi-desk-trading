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
