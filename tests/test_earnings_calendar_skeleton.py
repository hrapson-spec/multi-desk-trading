"""Earnings-calendar W10 skeleton test.

Phase 2 scale-out desk under the v1.16 roster. W10 skeleton ships with
a minimal ridge head; Gate 3 hot-swap + Controller raw-sum composition
with surface_positioning_feedback are the load-bearing invariants.
Gate 1/2 performance is weak by design until the earnings-event channel
lands in the sim (follow-on wave per commission §5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts.target_variables import VIX_30D_FORWARD_3D_DELTA
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from desks.base import DeskProtocol
from desks.earnings_calendar import ClassicalEarningsCalendarModel, EarningsCalendarDesk
from desks.surface_positioning_feedback import (
    ClassicalSurfacePositioningFeedbackModel,
    SurfacePositioningFeedbackDesk,
)
from eval import build_hot_swap_callables
from persistence import connect, init_db
from sim_equity_vrp import EquityObservationChannels, EquityVolMarket

NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=UTC)
BOOT_TS = NOW - timedelta(hours=1)


@pytest.fixture
def _channels():
    path = EquityVolMarket(n_days=400, seed=7).generate()
    return EquityObservationChannels.build(path, mode="clean", seed=7)


@pytest.fixture
def _fitted_desk(_channels):
    model = ClassicalEarningsCalendarModel()
    model.fit(_channels.market_price[:250])
    return EarningsCalendarDesk(model=model)


def test_earnings_calendar_conforms_to_desk_protocol():
    """Gate 3 precondition — the desk must satisfy the DeskProtocol."""
    desk = EarningsCalendarDesk()
    assert isinstance(desk, DeskProtocol)
    assert desk.target_variable == VIX_30D_FORWARD_3D_DELTA
    assert desk.event_id == "earnings_cluster"
    assert "earnings_calendar_feed" in desk.feed_names


def test_earnings_calendar_emits_signed_delta(_fitted_desk, _channels):
    """Fit + predict produces a signed 3-day vol-delta that composes
    with surface_positioning_feedback under raw-sum aggregation."""
    forecast = _fitted_desk.forecast_from_observation(_channels, 300, NOW)
    assert forecast.target_variable == VIX_30D_FORWARD_3D_DELTA
    assert forecast.directional_claim.sign in ("positive", "negative", "none")
    # point_estimate is a delta, not a vol level — may be negative.
    assert abs(forecast.point_estimate) < 100.0  # sanity bound on skeleton ridge


def test_earnings_calendar_passes_gate3_hot_swap(_fitted_desk, tmp_path: Path):
    """Gate 3 runtime hot-swap (v1.14): replacing this desk with a
    generic stub must preserve the Controller's decision flow."""
    conn = connect(tmp_path / "earnings_gate3.duckdb")
    init_db(conn)
    seed_cold_start(
        conn,
        desks=[(_fitted_desk.name, _fitted_desk.target_variable)],
        regime_ids=["regime_boot"],
        boot_ts=BOOT_TS,
    )
    real_forecast = Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=NOW,
        target_variable=VIX_30D_FORWARD_3D_DELTA,
        horizon=EventHorizon(
            event_id="earnings_cluster",
            expected_ts_utc=NOW + timedelta(days=3),
        ),
        point_estimate=0.5,
        uncertainty=UncertaintyInterval(level=0.8, lower=-1.0, upper=2.0),
        directional_claim=DirectionalClaim(
            variable=VIX_30D_FORWARD_3D_DELTA, sign="positive"
        ),
        staleness=False,
        confidence=0.55,
        provenance=Provenance(
            desk_name=_fitted_desk.name,
            model_name="skeleton_earnings_calendar",
            model_version="0.1.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        ),
    )
    regime_label = RegimeLabel(
        classification_ts_utc=NOW,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=Provenance(
            desk_name="regime_classifier",
            model_name="stub",
            model_version="0.0.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        ),
    )
    real_fn, stub_fn = build_hot_swap_callables(
        conn=conn,
        real_desk=_fitted_desk,
        real_forecast=real_forecast,
        regime_label=regime_label,
        recent_forecasts_other={},
        now_utc=NOW,
    )
    # Both closures should execute without raising and produce Decisions.
    assert real_fn() is True
    assert stub_fn() is True
    conn.close()


def test_earnings_calendar_composes_with_surface_positioning(_channels):
    """Both equity desks emit VIX_30D_FORWARD_3D_DELTA. Their forecasts
    must compose under the Controller's raw-sum aggregation — verified
    by constructing two forecasts and checking they both pass bus-side
    validation against the same target_variable registry entry."""
    earnings_model = ClassicalEarningsCalendarModel()
    earnings_model.fit(_channels.market_price[:250])
    earnings_desk = EarningsCalendarDesk(model=earnings_model)

    spf_model = ClassicalSurfacePositioningFeedbackModel()
    spf_obs = _channels.by_desk["surface_positioning_feedback"].components
    spf_model.fit(
        spf_obs["dealer_flow"][:250],
        spf_obs["vega_exposure"][:250],
        spf_obs["hedging_demand_level"][:250],
        spf_obs["put_skew_proxy"][:250],
        _channels.market_price[:250],
    )
    spf_desk = SurfacePositioningFeedbackDesk(model=spf_model)

    earnings_forecast = earnings_desk.forecast_from_observation(_channels, 300, NOW)
    spf_forecast = spf_desk.forecast_from_observation(_channels, 300, NOW)

    # Same target-variable registry entry → Controller can raw-sum their
    # point_estimates without unit reconciliation.
    assert earnings_forecast.target_variable == spf_forecast.target_variable
    assert earnings_forecast.target_variable == VIX_30D_FORWARD_3D_DELTA
