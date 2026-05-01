"""Earnings-calendar desk tests (v1.16 X1).

Previously `test_earnings_calendar_skeleton.py` — renamed at X1 ship
(2026-04-22) when the earnings-event channel landed and the desk moved
from structural skeleton to a real alpha-emitting desk. D-17 closed.

Test matrix:
- DeskProtocol conformance (unchanged from W10).
- Signed-delta emission (unchanged from W10; now uses the real channel).
- Gate 3 hot-swap (unchanged from W10).
- Raw-sum composition with surface_positioning_feedback (unchanged from W10).
- **NEW at X1**: Gate 1 skill against `zero_return_baseline` — D-17 closure evidence.
- **NEW at X1**: sim-channel shape / dtype / event-rate / forward-correlation / RNG isolation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from contracts.target_variables import VIX_30D_FORWARD_3D_DELTA
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Print,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import seed_cold_start
from desks.base import DeskProtocol
from desks.earnings_calendar import ClassicalEarningsCalendarModel, EarningsCalendarDesk
from desks.surface_positioning_feedback import (
    ClassicalSurfacePositioningFeedbackModel,
    SurfacePositioningFeedbackDesk,
)
from eval import build_hot_swap_callables
from eval.data import zero_return_baseline
from eval.gates import gate_skill_vs_baseline
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
    ec_obs = _channels.by_desk["earnings_calendar"].components
    model.fit(
        ec_obs["earnings_event_indicator"][:250],
        ec_obs["earnings_cluster_size"][:250],
        _channels.market_price[:250],
    )
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
    assert abs(forecast.point_estimate) < 100.0  # sanity bound on ridge output


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
            model_name="earnings_calendar_v1",
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
    assert real_fn() is True
    assert stub_fn() is True
    conn.close()


def test_earnings_calendar_composes_with_surface_positioning(_channels):
    """Both equity desks emit VIX_30D_FORWARD_3D_DELTA. Their forecasts
    must compose under the Controller's raw-sum aggregation — verified
    by constructing two forecasts and checking they both pass bus-side
    validation against the same target_variable registry entry."""
    earnings_model = ClassicalEarningsCalendarModel()
    ec_obs = _channels.by_desk["earnings_calendar"].components
    earnings_model.fit(
        ec_obs["earnings_event_indicator"][:250],
        ec_obs["earnings_cluster_size"][:250],
        _channels.market_price[:250],
    )
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

    assert earnings_forecast.target_variable == spf_forecast.target_variable
    assert earnings_forecast.target_variable == VIX_30D_FORWARD_3D_DELTA


def test_earnings_calendar_gate1_skill_on_new_channel():
    """X1 D-17 closure evidence: with the real earnings channel, the
    fitted desk must beat the zero-return baseline on held-out Gate 1
    (skill vs baseline, RMSE). Drives 30 forecasts on days
    250..280 of a 400-day path fit on the first 250 days."""
    path = EquityVolMarket(n_days=400, seed=7).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=7)
    ec_obs = channels.by_desk["earnings_calendar"].components

    model = ClassicalEarningsCalendarModel(horizon_days=3)
    model.fit(
        ec_obs["earnings_event_indicator"][:250],
        ec_obs["earnings_cluster_size"][:250],
        channels.market_price[:250],
    )
    desk = EarningsCalendarDesk(model=model)

    forecasts: list[Forecast] = []
    prints: list[Print] = []
    for i in range(250, 280):
        emission_ts = NOW + timedelta(days=i)
        realised_ts = emission_ts + timedelta(days=3)
        f = desk.forecast_from_observation(channels, i, emission_ts)
        forecasts.append(f)
        realised_delta = float(channels.market_price[i + 3] - channels.market_price[i - 1])
        prints.append(
            Print(
                print_id=f"earnings-{i:04d}",
                realised_ts_utc=realised_ts,
                target_variable=VIX_30D_FORWARD_3D_DELTA,
                value=realised_delta,
            )
        )

    baseline_fn = zero_return_baseline()
    result = gate_skill_vs_baseline(forecasts, prints, baseline_fn, metric="rmse")
    print(
        "\nX1 Gate 1 skill (earnings_calendar vs zero-return baseline): "
        f"desk_rmse={result.metrics['desk_metric']:.4f} "
        f"baseline_rmse={result.metrics['baseline_metric']:.4f} "
        f"rel_improvement={result.metrics['relative_improvement']:.4f} "
        f"passed={result.passed}"
    )
    assert result.passed, (
        "earnings_calendar Gate 1 must beat zero-return baseline post-X1. "
        f"Metrics: {result.metrics}"
    )
    assert result.metrics["relative_improvement"] > 0.0, (
        f"Expected relative improvement > 0; got {result.metrics}"
    )


# ---------------------------------------------------------------------------
# v1.16 X1 — sim-channel decision-time safety tests.
# ---------------------------------------------------------------------------


def test_earnings_channel_shapes_and_event_rate(_channels):
    """earnings_event_indicator + earnings_cluster_size must have the
    expected shapes, dtypes, and a non-trivial event rate."""
    ec_obs = _channels.by_desk["earnings_calendar"].components
    indicator = ec_obs["earnings_event_indicator"]
    cluster_size = ec_obs["earnings_cluster_size"]
    assert indicator.shape == (400,)
    assert cluster_size.shape == (400,)
    assert indicator.dtype == np.int8
    assert cluster_size.dtype == np.int16
    rate = float(indicator.mean())
    # Expected event rate with threshold=1.2 on unit-variance Gaussian:
    # 1 - Φ(1.2) ≈ 11.5%. Tolerance for finite-sample variation.
    assert 0.05 <= rate <= 0.18, f"event rate {rate:.4f} outside [0.05, 0.18]"


def test_earnings_channel_correlates_with_future_vol():
    """X1 mechanism invariant: earnings_cluster_size[t] positively
    correlates with vol_level[t + 3]. Required for the desk to have any
    Gate 1 skill — the sim's forward-correlation design is the source."""
    path = EquityVolMarket(n_days=1500, seed=42).generate()
    cluster_size = path.earnings_cluster_size
    vol_future = path.vol_level[3:]
    cluster_now = cluster_size[:-3]
    r = float(np.corrcoef(cluster_now[50:], vol_future[50:])[0, 1])
    print(f"\nX1 cluster_size[t] vs vol_level[t+3] Pearson r = {r:.4f}")
    assert r > 0.08, (
        f"Expected positive forward correlation (earnings predict future vol); got r={r:.4f}"
    )


def test_earnings_rng_isolated_from_existing_streams():
    """D12 preservation guarantee: mutating earnings_vol_corr must NOT
    change vol_level, dealer_flow, vega_exposure, or hedging_demand
    bytes. Proves the new generation happens AFTER existing draws with
    an isolated RNG stream."""
    from sim_equity_vrp import EquityVolMarketConfig

    default_path = EquityVolMarket(n_days=300, seed=3).generate()
    tweaked_path = EquityVolMarket(
        n_days=300,
        seed=3,
        config=EquityVolMarketConfig(
            earnings_vol_corr=0.9,  # wildly different from default 0.45
            earnings_event_threshold=0.1,  # far more events
            earnings_cluster_window=20,  # wider window
        ),
    ).generate()
    # All pre-X1 arrays must match byte-identically.
    np.testing.assert_array_equal(default_path.vol_level, tweaked_path.vol_level)
    np.testing.assert_array_equal(default_path.dealer_flow, tweaked_path.dealer_flow)
    np.testing.assert_array_equal(default_path.vega_exposure, tweaked_path.vega_exposure)
    np.testing.assert_array_equal(default_path.spot_log_price, tweaked_path.spot_log_price)
    np.testing.assert_array_equal(default_path.hedging_demand, tweaked_path.hedging_demand)
    np.testing.assert_array_equal(default_path.put_skew_proxy, tweaked_path.put_skew_proxy)
    # Earnings arrays should differ (proves the tweak took effect).
    assert not np.array_equal(
        default_path.earnings_event_indicator, tweaked_path.earnings_event_indicator
    )
