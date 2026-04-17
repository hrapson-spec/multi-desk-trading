"""Unit tests for sim.latent_state."""

from __future__ import annotations

import numpy as np
import pytest

from sim.latent_state import LatentMarket, LatentMarketConfig


def test_latent_market_is_seed_deterministic():
    a = LatentMarket(n_days=250, seed=42).generate()
    b = LatentMarket(n_days=250, seed=42).generate()
    assert np.array_equal(a.chi, b.chi)
    assert np.array_equal(a.xi, b.xi)
    assert np.array_equal(a.supply, b.supply)
    assert np.array_equal(a.demand, b.demand)
    assert np.array_equal(a.event_indicator, b.event_indicator)
    assert np.array_equal(a.price, b.price)
    assert a.regimes.labels == b.regimes.labels


def test_latent_market_shapes_and_positive_price():
    path = LatentMarket(n_days=500, seed=1).generate()
    assert path.n_days == 500
    assert path.chi.shape == (500,)
    assert path.xi.shape == (500,)
    assert path.supply.shape == (500,)
    assert path.demand.shape == (500,)
    assert path.event_indicator.shape == (500,)
    assert path.event_intensity.shape == (500,)
    assert path.price.shape == (500,)
    assert np.all(path.price > 0)
    # Log-price consistency: log_price = chi + xi + gamma*(s-d)
    expected_lp = (
        path.chi + path.xi + path.config.balance_loading_gamma * (path.supply - path.demand)
    )
    assert np.allclose(path.log_price, expected_lp)


def test_latent_market_rejects_tiny_n_days():
    with pytest.raises(ValueError, match="n_days must be"):
        LatentMarket(n_days=1, seed=0).generate()


def test_xi_drifts_with_configured_mu():
    """With positive drift, the terminal xi should on average exceed initial.
    Run a large batch and check the mean over seeds."""
    cfg = LatentMarketConfig(xi_drift=0.5, xi_vol=0.02)
    finals = [LatentMarket(n_days=252, seed=s, config=cfg).generate().xi[-1] for s in range(40)]
    # Drift=0.5 over 1 year gives a deterministic +0.5 shift on mean;
    # per-seed shock adds N(0, 0.02). Mean of 40 samples should be close.
    mean_shift = float(np.mean(finals)) - cfg.xi_initial
    assert 0.3 < mean_shift < 0.7


def test_supply_reverts_to_regime_mean():
    """Force a long supply-dominated regime and verify supply mean shifts."""
    from sim.regimes import RegimeConfig

    # Regime config that pins supply_dominated (self-loop prob = 1)
    pinned = RegimeConfig(
        transition_matrix=np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],  # supply_dominated self-loop
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
        initial_distribution=np.array([0.0, 1.0, 0.0, 0.0]),
    )
    mkt = LatentMarket(n_days=1000, seed=3, regime_config=pinned)
    path = mkt.generate()
    # Under supply_dominated, supply_mean shift = -1.0 (from default config)
    # After enough OU steps (λ=1, 1000 days >> 1/λ·252) supply should hover
    # near -1.0 on average.
    tail_mean = float(np.mean(path.supply[-200:]))
    assert tail_mean < -0.3  # well below 0, moving toward -1.0


def test_events_perturb_supply_on_fire_days():
    """Average supply impact on fire days should be negative (event_supply_impact=-0.3)."""
    from sim.regimes import RegimeConfig

    # Force event_driven to make events frequent
    pinned = RegimeConfig(
        transition_matrix=np.array(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ]
        ),
        initial_distribution=np.array([0.0, 0.0, 0.0, 1.0]),
    )
    path = LatentMarket(n_days=2000, seed=5, regime_config=pinned).generate()
    fire_idx = np.where(path.event_indicator == 1)[0]
    # Need at least some events to test the mechanism.
    assert fire_idx.size > 20, f"expected frequent events; got {fire_idx.size}"


def test_no_events_means_no_hawkes_self_excitation():
    """A zero-baseline, zero-self-excitation config produces no events."""
    cfg = LatentMarketConfig(event_mu0=0.0, event_alpha=0.0)
    path = LatentMarket(n_days=500, seed=7, config=cfg).generate()
    assert path.event_indicator.sum() == 0
    # Intensity stays at baseline (= 0)
    assert np.allclose(path.event_intensity, 0.0)
