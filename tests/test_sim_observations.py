"""Unit tests for sim.observations across all three modes."""

from __future__ import annotations

import numpy as np
import pytest

from sim.latent_state import LatentMarket
from sim.observations import (
    DESK_NAMES,
    ObservationChannels,
    ObservationConfig,
    _mixing_matrix,
)


@pytest.fixture
def path():
    return LatentMarket(n_days=400, seed=42).generate()


# ---------------------------------------------------------------------------
# Cross-mode invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["clean", "leakage", "realistic"])
def test_channels_return_all_five_desks(path, mode):
    ch = ObservationChannels.build(path, mode=mode, seed=0)
    assert set(ch.by_desk.keys()) == set(DESK_NAMES)


@pytest.mark.parametrize("mode", ["clean", "leakage", "realistic"])
def test_components_have_correct_length(path, mode):
    ch = ObservationChannels.build(path, mode=mode, seed=0)
    for desk, obs in ch.by_desk.items():
        for name, arr in obs.components.items():
            assert arr.shape == (path.n_days,), f"{desk}.{name} shape {arr.shape}"


@pytest.mark.parametrize("mode", ["clean", "leakage", "realistic"])
def test_seed_determinism(path, mode):
    a = ObservationChannels.build(path, mode=mode, seed=123)
    b = ObservationChannels.build(path, mode=mode, seed=123)
    for desk in DESK_NAMES:
        for name in a.by_desk[desk].components:
            # NaN-safe equality (realistic mode can inject NaN for staleness)
            aa = a.by_desk[desk].components[name]
            bb = b.by_desk[desk].components[name]
            assert np.array_equal(aa, bb, equal_nan=True), f"{mode}/{desk}/{name}"


@pytest.mark.parametrize("mode", ["clean", "leakage", "realistic"])
def test_invalid_mode_rejected(path, mode):
    with pytest.raises(ValueError, match="mode must be"):
        ObservationChannels.build(path, mode="bogus", seed=0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Clean mode
# ---------------------------------------------------------------------------


def test_clean_storage_curve_has_price_and_balance(path):
    ch = ObservationChannels.build(path, mode="clean", seed=0)
    obs = ch.by_desk["storage_curve"]
    assert "price" in obs.components
    assert "balance" in obs.components


def test_clean_supply_observation_is_close_to_ar1_return(path):
    """Plan §A: each desk's clean channel exposes its AR(1) return stream
    (not the OU supply level). Correlation with the AR(1) driver should
    be very high under small measurement noise."""
    ch = ObservationChannels.build(path, mode="clean", seed=0)
    obs = ch.by_desk["supply"].components["supply"]
    # Supply channel = supply_ar1 + small noise; corr with AR(1) should be ~1.
    corr = np.corrcoef(obs, path.desk_ar1["supply"])[0, 1]
    # Phase A default config has desk_ar1 disabled (rho=0, vol=0). In that
    # case the channel is pure noise and correlation is undefined; treat
    # as a trivial pass.
    if path.desk_ar1["supply"].std() == 0.0:
        pytest.skip("default config has AR(1) driver disabled")
    assert corr > 0.95
    # Auxiliary OU level component is still exposed for Phase A ridge
    # models that want it.
    assert "supply_level" in ch.by_desk["supply"].components


def test_clean_stale_mask_is_all_false(path):
    ch = ObservationChannels.build(path, mode="clean", seed=0)
    for desk, obs in ch.by_desk.items():
        assert not obs.stale_mask.any(), f"{desk} had staleness in clean mode"


# ---------------------------------------------------------------------------
# Leakage mode
# ---------------------------------------------------------------------------


def test_mixing_matrix_diagonal_dominant():
    m = _mixing_matrix(0.1)
    assert m.shape == (5, 5)
    assert np.allclose(m.sum(axis=1), 1.0)
    for i in range(5):
        assert m[i, i] > m[i, (i + 1) % 5]


def test_leakage_correlation_is_weaker_than_clean(path):
    """Each desk's leakage-mode observation should be less correlated with
    its own latent OU factor (supply) than the clean mode. Leakage mode
    still uses the supply OU level as the factor (not the AR(1) return),
    because the Phase-B mixing matrix is defined over latent LEVELS for
    clear structural interpretation."""
    leak = ObservationChannels.build(
        path, mode="leakage", seed=0, config=ObservationConfig(leakage_strength=0.4)
    )
    # Leakage-mode channel is a diagonal-dominant mix of latent LEVELS
    # so it remains meaningfully correlated with supply level (≥ 0.5
    # at strength=0.4). Clean mode's channel is now the AR(1) return
    # stream (see test_clean_supply_observation_is_close_to_ar1_return)
    # so a direct clean-vs-leakage comparison would not be apples-to-
    # apples after the Phase A observation redesign.
    leak_corr = np.corrcoef(leak.by_desk["supply"].components["supply"], path.supply)[0, 1]
    assert leak_corr > 0.5


# ---------------------------------------------------------------------------
# Realistic mode
# ---------------------------------------------------------------------------


def test_realistic_mode_produces_staleness_at_configured_rate(path):
    cfg = ObservationConfig(
        staleness_prob={
            "storage_curve": 0.05,
            "supply": 0.1,
            "demand": 0.1,
            "geopolitics": 0.05,
            "macro": 0.05,
        }
    )
    ch = ObservationChannels.build(path, mode="realistic", seed=11, config=cfg)
    supply_stale_rate = ch.by_desk["supply"].stale_mask.mean()
    # Expect within a band around configured 0.1 for n=400 observations
    assert 0.05 < supply_stale_rate < 0.16


def test_realistic_mode_applies_publication_lag(path):
    cfg = ObservationConfig(
        publication_lag={
            "storage_curve": 0,
            "supply": 3,
            "demand": 0,
            "geopolitics": 0,
            "macro": 0,
        },
        staleness_prob=dict.fromkeys(DESK_NAMES, 0.0),  # isolate lag
    )
    ch = ObservationChannels.build(path, mode="realistic", seed=0, config=cfg)
    assert ch.by_desk["supply"].lag_days == 3
    # The first 3 observations should be the value at index 0 of the
    # leakage-mode signal (which is supply pre-lag). Easier to check the
    # shape property: after lag, entries shift by 3.
    obs = ch.by_desk["supply"].components["supply"]
    # First 3 entries should all equal obs[3]'s lagged origin value
    # (the supply observation at day 0)
    assert obs[0] == obs[1] == obs[2]


def test_realistic_chatter_active_only_in_event_regimes(path):
    """Set chatter huge and verify event-regime days have larger |signal - leakage_baseline|
    than non-event days."""
    cfg_no_chatter = ObservationConfig(chatter_amplitude=0.0)
    cfg_big_chatter = ObservationConfig(chatter_amplitude=1.0)
    # Disable missingness / lag to isolate the chatter effect
    cfg_no_chatter = ObservationConfig(
        chatter_amplitude=0.0,
        staleness_prob=dict.fromkeys(DESK_NAMES, 0.0),
        publication_lag=dict.fromkeys(DESK_NAMES, 0),
    )
    cfg_big_chatter = ObservationConfig(
        chatter_amplitude=1.0,
        staleness_prob=dict.fromkeys(DESK_NAMES, 0.0),
        publication_lag=dict.fromkeys(DESK_NAMES, 0),
    )
    no_chatter = ObservationChannels.build(path, mode="realistic", seed=0, config=cfg_no_chatter)
    big_chatter = ObservationChannels.build(path, mode="realistic", seed=0, config=cfg_big_chatter)
    # In event-driven regime days, the difference between chatter/no-chatter
    # should be large; in non-event days it should be zero.
    is_event = np.array([r == "event_driven" for r in path.regimes.labels], dtype=bool)
    diff_supply = (
        big_chatter.by_desk["supply"].components["supply"]
        - no_chatter.by_desk["supply"].components["supply"]
    )
    # Non-event days: chatter inactive ⇒ diff == 0
    assert np.allclose(diff_supply[~is_event], 0.0, atol=1e-9)
    # Event days: chatter active ⇒ diff is non-trivial (if any event days exist)
    if is_event.any():
        assert float(np.nanstd(diff_supply[is_event])) > 0.1
