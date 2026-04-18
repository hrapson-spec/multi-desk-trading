"""Tests for sim_equity_vrp (Phase 2 MVP synthetic equity-vol market)."""

from __future__ import annotations

import numpy as np
import pytest

from sim_equity_vrp import (
    VOL_REGIMES,
    EquityObservationChannels,
    EquityVolMarket,
    VolRegimeConfig,
)


def test_vol_regimes_distinct_from_oil_regimes():
    """String regimes must not collide with oil's REGIMES — otherwise
    SignalWeight rows could shadow each other if the two domains ever
    shared a DuckDB file."""
    from sim.regimes import REGIMES as OIL_REGIMES

    assert set(VOL_REGIMES).isdisjoint(set(OIL_REGIMES)), (
        f"VOL_REGIMES {VOL_REGIMES} collide with OIL_REGIMES {OIL_REGIMES}"
    )


def test_equity_vol_market_is_seed_deterministic():
    a = EquityVolMarket(n_days=100, seed=42).generate()
    b = EquityVolMarket(n_days=100, seed=42).generate()
    np.testing.assert_array_equal(a.vol_level, b.vol_level)
    np.testing.assert_array_equal(a.dealer_flow, b.dealer_flow)
    np.testing.assert_array_equal(a.vega_exposure, b.vega_exposure)
    np.testing.assert_array_equal(a.spot_log_price, b.spot_log_price)


def test_equity_vol_market_different_seeds_differ():
    a = EquityVolMarket(n_days=100, seed=1).generate()
    b = EquityVolMarket(n_days=100, seed=2).generate()
    assert not np.array_equal(a.vol_level, b.vol_level)


def test_equity_vol_path_has_correct_shapes():
    path = EquityVolMarket(n_days=500, seed=0).generate()
    assert path.n_days == 500
    assert path.vol_level.shape == (500,)
    assert path.dealer_flow.shape == (500,)
    assert path.vega_exposure.shape == (500,)
    assert path.spot_log_price.shape == (500,)
    assert len(path.regimes.labels) == 500


def test_vol_level_is_positive():
    """Vol is clipped to stay ≥ 1.0 (no negative vols)."""
    path = EquityVolMarket(n_days=1000, seed=5).generate()
    assert (path.vol_level >= 1.0).all()


def test_stress_regime_has_higher_mean_vol():
    """Architectural sanity: stress regimes should show higher average
    vol than quiet. Validates the regime_scaling hookup."""
    path = EquityVolMarket(n_days=3000, seed=7).generate()
    labels = np.array(list(path.regimes.labels))
    quiet_mask = labels == "vol_quiet"
    stress_mask = labels == "vol_stress"
    # Require non-trivial coverage of both regimes.
    if quiet_mask.sum() < 100 or stress_mask.sum() < 100:
        pytest.skip("seed 7 did not cover both regimes with enough mass")
    mean_quiet = path.vol_level[quiet_mask].mean()
    mean_stress = path.vol_level[stress_mask].mean()
    assert mean_stress > mean_quiet, (
        f"stress mean vol {mean_stress:.1f} should exceed quiet {mean_quiet:.1f}"
    )


def test_dealer_flow_predicts_vol_change():
    """The MVP's load-bearing economic claim: dealer_flow at t
    correlates positively with vol shock at t+1 (from config.flow_vol_corr=0.35)."""
    path = EquityVolMarket(n_days=5000, seed=11).generate()
    vol_shocks = np.diff(path.vol_level)
    flow_lead = path.dealer_flow[:-1]  # flow at t predicts vol[t+1] − vol[t]
    corr = float(np.corrcoef(flow_lead, vol_shocks)[0, 1])
    # With flow_vol_corr=0.35 + noise from vol OU mean-reversion + regime
    # scaling, the realised correlation will be < 0.35 but still positive
    # and detectable over 5000 obs.
    assert corr > 0.05, f"dealer_flow → vol-change correlation too weak: {corr:.3f}"


def test_regime_config_transition_matrix_rows_sum_to_one():
    cfg = VolRegimeConfig()
    row_sums = cfg.transition_matrix.sum(axis=1)
    np.testing.assert_allclose(row_sums, np.ones(3), atol=1e-9)


def test_observation_channels_clean_mode():
    path = EquityVolMarket(n_days=200, seed=0).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=0)
    assert channels.mode == "clean"
    assert channels.market_price.shape == (200,)
    # Market price equals vol_level exactly (no observation noise on Prints).
    np.testing.assert_array_equal(channels.market_price, path.vol_level)
    # dealer_inventory desk channels.
    assert "dealer_inventory" in channels.by_desk
    obs = channels.by_desk["dealer_inventory"]
    assert set(obs.components.keys()) == {"dealer_flow", "vega_exposure"}
    assert obs.components["dealer_flow"].shape == (200,)
    assert obs.components["vega_exposure"].shape == (200,)


def test_observation_channels_rejects_unimplemented_modes():
    path = EquityVolMarket(n_days=100, seed=0).generate()
    with pytest.raises(NotImplementedError, match="not implemented for Phase 2 MVP"):
        EquityObservationChannels.build(path, mode="leakage")  # type: ignore[arg-type]
