"""Load-bearing test (spec §4.5).

Imports only: contracts/v1, contracts/target_variables, bus, persistence,
grading. Mocks every desk as an inline emit() producing valid Forecast
objects. Asserts the pipeline runs end-to-end against stubs.

If this test ever needs to import a desks/ submodule to pass, the boundary
has drifted and the v1.2 capability claim is broken.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from bus import Bus
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    ControllerParams,
    Decision,
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Print,
    Provenance,
    SignalWeight,
    UncertaintyInterval,
)
from grading import grade
from persistence import (
    connect,
    count_rows,
    get_latest_controller_params,
    get_latest_signal_weights,
    init_db,
)

DESK_NAMES = [
    "supply",
    "demand",
    "storage_curve",
    "geopolitics",
    "macro",
    "regime_classifier",
]


def _prov(desk_name: str) -> Provenance:
    return Provenance(
        desk_name=desk_name,
        model_name="stub",
        model_version="0.0.0",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def _stub_forecast(desk_name: str, now: datetime) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=now,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="eia_wpsr", expected_ts_utc=now + timedelta(days=7)),
        point_estimate=0.0,
        uncertainty=UncertaintyInterval(level=0.8, lower=-1e9, upper=1e9),
        directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="none"),
        staleness=True,
        confidence=0.5,
        provenance=_prov(desk_name),
    )


def test_controller_runs_end_to_end_against_stubs(tmp_db_path):
    # ---- Track which modules get imported during the run ----
    desks_imported_before = {k for k in sys.modules if k.startswith("desks.") or k == "desks"}

    # ---- Set up pipeline ----
    conn = connect(tmp_db_path)
    init_db(conn)
    bus = Bus(conn, mode="development")
    now = datetime(2026, 1, 7, 15, 0, 0, tzinfo=UTC)

    # Six stub desks emit one Forecast each.
    forecast_ids: list[str] = []
    for desk in DESK_NAMES:
        f = _stub_forecast(desk, now)
        bus.publish_forecast(f)
        forecast_ids.append(f.forecast_id)

    # Cold-start uniform weights for regime_boot (spec §14.8).
    for desk in DESK_NAMES:
        bus.publish_signal_weight(
            SignalWeight(
                weight_id=str(uuid.uuid4()),
                regime_id="regime_boot",
                desk_name=desk,
                target_variable=WTI_FRONT_MONTH_CLOSE,
                weight=1.0 / len(DESK_NAMES),
                promotion_ts_utc=now,
                validation_artefact="cold_start",
            )
        )
    bus.publish_controller_params(
        ControllerParams(
            params_id=str(uuid.uuid4()),
            regime_id="regime_boot",
            k_regime=1.0,
            pos_limit_regime=100.0,
            promotion_ts_utc=now,
            validation_artefact="cold_start",
        )
    )

    # Controller decision: linear sizing.
    weights = get_latest_signal_weights(conn, "regime_boot")
    params = get_latest_controller_params(conn, "regime_boot")
    assert params is not None
    # combined_signal = sum(weight × point_estimate). All stubs emit 0.0.
    combined_signal = sum(w["weight"] * 0.0 for w in weights)
    position_size = max(
        min(params["k_regime"] * combined_signal, params["pos_limit_regime"]),
        -params["pos_limit_regime"],
    )
    bus.publish_decision(
        Decision(
            decision_id=str(uuid.uuid4()),
            emission_ts_utc=now + timedelta(minutes=1),
            regime_id="regime_boot",
            combined_signal=combined_signal,
            position_size=position_size,
            input_forecast_ids=forecast_ids,
            provenance=_prov("controller"),
        )
    )

    # Print arrives; grade each desk's forecast.
    p = Print(
        print_id=str(uuid.uuid4()),
        realised_ts_utc=now + timedelta(days=7),
        target_variable=WTI_FRONT_MONTH_CLOSE,
        value=0.0,
        event_id="eia_wpsr",
    )
    bus.publish_print(p)

    # Pull forecasts and grade.
    from persistence.db import replay_forecasts

    for f_row in replay_forecasts(conn, now - timedelta(hours=1), now + timedelta(hours=1)):
        # Reconstruct Forecast from row for grading
        assert f_row["horizon_kind"] == "event"
        f = Forecast(
            forecast_id=f_row["forecast_id"],
            emission_ts_utc=f_row["emission_ts_utc"],
            target_variable=f_row["target_variable"],
            horizon=EventHorizon(**f_row["horizon_payload"]),
            point_estimate=f_row["point_estimate"],
            uncertainty=UncertaintyInterval(**f_row["uncertainty"]),
            directional_claim=DirectionalClaim(**f_row["directional_claim"]),
            staleness=f_row["staleness"],
            confidence=f_row["confidence"],
            provenance=Provenance(**f_row["provenance"]),
        )
        g = grade(f, p, grading_ts_utc=now + timedelta(days=7, hours=1))
        bus.publish_grade(g)

    # ---- Assertions ----
    assert count_rows(conn, "forecasts") == len(DESK_NAMES)
    assert count_rows(conn, "prints") == 1
    assert count_rows(conn, "decisions") == 1
    assert count_rows(conn, "grades") == len(DESK_NAMES)
    assert count_rows(conn, "signal_weights") == len(DESK_NAMES)
    assert count_rows(conn, "controller_params") == 1

    # ---- No desks/* module was imported during the run ----
    desks_imported_after = {k for k in sys.modules if k.startswith("desks.") or k == "desks"}
    newly_imported = desks_imported_after - desks_imported_before
    assert newly_imported == set(), (
        f"Boundary violated: desks modules imported during test: {newly_imported}"
    )

    conn.close()


__all__: list[Callable[..., None]] = []
