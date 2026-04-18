"""B-4 regression: Controller.decide() must exclude retired desks
from Decision.input_forecast_ids (spec v1.14).

Latent bug discovered during D9 design review: `controller/decision.py`
appends `forecast_id` to `contributing_ids` unconditionally after the
`f.staleness` guard, not after the weight check. Under the production
retire path (`remediation.retire_desk_for_regime` writes a zero-weight
SignalWeight row), a retired desk's non-stale forecast contributes 0
to combined_signal but still flows into contributing_ids —
contaminating downstream Shapley attribution and audit trails.

This test pins the correct semantics: a retired desk (weight=0) must
NOT appear in input_forecast_ids regardless of the forecast's
staleness status.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence.db import connect, init_db
from research_loop.remediation import retire_desk_for_regime

BOOT_TS = datetime(2026, 4, 18, 9, 0, 0, 123456, tzinfo=UTC)
NOW_TS = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)
RETIRE_TS = datetime(2026, 4, 18, 10, 1, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "retire_regress.duckdb")
    init_db(c)
    yield c
    c.close()


def _prov(desk: str) -> Provenance:
    return Provenance(
        desk_name=desk,
        model_name="m",
        model_version="0.1",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def _fcast(desk: str, value: float, emission_ts: datetime) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=emission_ts,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=emission_ts),
        point_estimate=value,
        uncertainty=UncertaintyInterval(level=0.8, lower=value - 5.0, upper=value + 5.0),
        directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
        staleness=False,
        confidence=1.0,
        provenance=_prov(desk),
    )


def _regime(ts: datetime) -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=ts,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def test_retired_desk_not_in_contributing_ids(conn):
    """Pre-retire: storage_curve + supply both contribute to the Decision.
    After retire_desk_for_regime writes a zero-weight SignalWeight row
    for supply, the next Controller.decide() call must NOT include
    supply's forecast_id in input_forecast_ids — even though the
    forecast itself is non-stale."""
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=BOOT_TS,
    )

    ctrl = Controller(conn=conn)
    sc_forecast = _fcast("storage_curve", 82.0, NOW_TS)
    sup_forecast = _fcast("supply", 78.0, NOW_TS)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): sc_forecast,
        ("supply", WTI_FRONT_MONTH_CLOSE): sup_forecast,
    }

    # --- Pre-retire: both desks contribute ------------------------------
    d_pre = ctrl.decide(now_utc=NOW_TS, regime_label=_regime(NOW_TS), recent_forecasts=recent)
    assert sc_forecast.forecast_id in d_pre.input_forecast_ids
    assert sup_forecast.forecast_id in d_pre.input_forecast_ids
    # Uniform-weight: combined_signal = 0.5*82 + 0.5*78 = 80.
    assert d_pre.combined_signal == pytest.approx(80.0)

    # --- Retire supply --------------------------------------------------
    retire_desk_for_regime(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="test_retire_exclusion",
        now_utc=RETIRE_TS,
    )

    # --- Post-retire: supply MUST NOT appear in contributing_ids --------
    d_post = ctrl.decide(
        now_utc=RETIRE_TS, regime_label=_regime(RETIRE_TS), recent_forecasts=recent
    )
    assert sc_forecast.forecast_id in d_post.input_forecast_ids
    assert sup_forecast.forecast_id not in d_post.input_forecast_ids, (
        "Retired desk's forecast_id leaked into contributing_ids — "
        "controller/decision.py missing weight=0 exclusion guard"
    )
    # combined_signal = 0.5 * 82 + 0.0 * 78 = 41.0 (supply weight=0).
    assert d_post.combined_signal == pytest.approx(41.0)


def test_retired_desk_stale_forecast_also_excluded(conn):
    """Defensive companion: retired desk + stale forecast → also
    excluded. Same exclusion outcome, different code path."""
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=BOOT_TS,
    )
    retire_desk_for_regime(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="test_retire_stale",
        now_utc=RETIRE_TS,
    )

    ctrl = Controller(conn=conn)
    sc_forecast = _fcast("storage_curve", 82.0, NOW_TS)
    stale_sup = Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=NOW_TS,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=NOW_TS),
        point_estimate=78.0,
        uncertainty=UncertaintyInterval(level=0.8, lower=-1e9, upper=1e9),
        directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="none"),
        staleness=True,
        confidence=0.5,
        provenance=_prov("supply"),
    )
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): sc_forecast,
        ("supply", WTI_FRONT_MONTH_CLOSE): stale_sup,
    }
    d = ctrl.decide(now_utc=RETIRE_TS, regime_label=_regime(RETIRE_TS), recent_forecasts=recent)
    assert sc_forecast.forecast_id in d.input_forecast_ids
    assert stale_sup.forecast_id not in d.input_forecast_ids
