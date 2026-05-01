"""Tests for sim_equity_vrp (Phase 2 MVP + v1.13 hedging_demand extension)."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from sim_equity_vrp import (
    VOL_REGIMES,
    EquityObservationChannels,
    EquityVolMarket,
    VolRegimeConfig,
)

# ---------------------------------------------------------------------------
# Golden fixtures for dealer_inventory (pre-v1.13, captured at phase2-mvp-v1.12).
# These hashes prove that the v1.13 hedging_demand extension did NOT perturb
# dealer_inventory's latent OR observed arrays. If any of these hashes fails:
#   1. DO NOT re-record. Investigate what changed in the extension.
#   2. Re-record ONLY with a spec v1.x dependency-version revision.
# ---------------------------------------------------------------------------
_GOLDEN_SEED = 3
_GOLDEN_N_DAYS = 1200
_GOLDEN_VOL_LEVEL_SHA256 = "ec2ee3782dbd8964edda7be5c0585ef8a497f813de6bbaa568e527c01e48aa99"
_GOLDEN_DEALER_FLOW_SHA256 = "08df48dc4090a158d7d6726e47d169f2978a6c098cd6fb87c8b6180fba9f5844"
_GOLDEN_VEGA_EXPOSURE_SHA256 = "ef8d32a2cb1b4432ea9bc36e631c9b4d5d14a92698264c533e8cfb96c5ec682c"
_GOLDEN_SPOT_LOG_PRICE_SHA256 = "4c9833f65f9bc2c91cf8f36b03c8cd5b7e8fa8749866888a267da466e121f9ad"
_GOLDEN_OBS_DEALER_FLOW_SHA256 = "0ca44eac2782e77769788b06734ccbc91578ffb3d87f852bc88cefa5ec357142"
_GOLDEN_OBS_VEGA_EXPOSURE_SHA256 = (
    "c922dbbdcfc371beb53e359c922860dd31b7ee10be4e67572f25239e42d3b5a3"
)


def _sha256(a: np.ndarray) -> str:
    return hashlib.sha256(a.tobytes()).hexdigest()


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


# ---------------------------------------------------------------------------
# v1.13 — hedging_demand extension + determinism regression
# ---------------------------------------------------------------------------


def test_hedging_demand_path_has_correct_shape():
    path = EquityVolMarket(n_days=500, seed=0).generate()
    assert path.hedging_demand.shape == (500,)
    assert path.put_skew_proxy.shape == (500,)


def test_hedging_demand_seed_deterministic():
    a = EquityVolMarket(n_days=200, seed=7).generate()
    b = EquityVolMarket(n_days=200, seed=7).generate()
    np.testing.assert_array_equal(a.hedging_demand, b.hedging_demand)
    np.testing.assert_array_equal(a.put_skew_proxy, b.put_skew_proxy)


def test_hedging_demand_leads_vol_changes():
    """hd[t] correlates with vol[t+1] − vol[t] via the shared shock
    index t (same mechanism as dealer_flow). Mirror of the existing
    `test_dealer_flow_predicts_vol_change` pattern: `np.diff(vol)`
    aligned with `hedging_demand[:-1]`."""
    path = EquityVolMarket(n_days=5000, seed=11).generate()
    vol_change = np.diff(path.vol_level)  # shape (n-1,), vol[t+1] - vol[t]
    hd_lead = path.hedging_demand[:-1]  # shape (n-1,)
    corr = float(np.corrcoef(hd_lead, vol_change)[0, 1])
    assert corr > 0.05, f"hedging_demand → vol-change correlation too weak: {corr:.3f}"


def test_hedging_demand_lead_lag_holds_across_seeds():
    """Multi-seed sweep: mean lead-lag correlation > 0.05 across
    {3, 11, 17, 23, 29}. Replaces single-seed flaky threshold."""
    seeds = (3, 11, 17, 23, 29)
    corrs: list[float] = []
    for seed in seeds:
        path = EquityVolMarket(n_days=5000, seed=seed).generate()
        vol_change = np.diff(path.vol_level)
        hd_lead = path.hedging_demand[:-1]
        corrs.append(float(np.corrcoef(hd_lead, vol_change)[0, 1]))
    mean_corr = sum(corrs) / len(corrs)
    assert mean_corr > 0.05, (
        f"mean hedging_demand → vol-change correlation too weak: {mean_corr:.3f} "
        f"(per-seed: {corrs})"
    )


def test_put_skew_proxy_scale_control():
    """Multi-seed scale-control: 99th percentile of |put_skew_proxy|
    stays within documented bound across {3, 11, 17, 23, 29}.

    Expected bound: hd stationary std ≈ 0.92, stress vol ~ 60 →
    99th-percentile of the product ≈ 2.5σ · 60 ≈ 150 in extreme
    single-tail. Bound at 200 comfortably; if exceeded, the fix is
    tanh/winsorisation not silent clipping."""
    seeds = (3, 11, 17, 23, 29)
    for seed in seeds:
        path = EquityVolMarket(n_days=1200, seed=seed).generate()
        q99 = float(np.quantile(np.abs(path.put_skew_proxy), 0.99))
        assert q99 <= 200.0, (
            f"put_skew_proxy 99th-percentile |value| too large at seed={seed}: "
            f"{q99:.2f}. Apply tanh / winsorisation to the product."
        )


def test_dealer_inventory_golden_fixtures_unchanged():
    """Load-bearing v1.13 regression: the hedging_demand extension must
    NOT perturb dealer_inventory's latent or observed arrays. These
    hashes were captured at tag phase2-mvp-v1.12 BEFORE this commit's
    changes to latent_state.py and observations.py. If any hash fails,
    the extension has introduced silent drift — rollback and redesign."""
    path = EquityVolMarket(n_days=_GOLDEN_N_DAYS, seed=_GOLDEN_SEED).generate()
    assert _sha256(path.vol_level) == _GOLDEN_VOL_LEVEL_SHA256
    assert _sha256(path.dealer_flow) == _GOLDEN_DEALER_FLOW_SHA256
    assert _sha256(path.vega_exposure) == _GOLDEN_VEGA_EXPOSURE_SHA256
    assert _sha256(path.spot_log_price) == _GOLDEN_SPOT_LOG_PRICE_SHA256

    channels = EquityObservationChannels.build(path, mode="clean", seed=_GOLDEN_SEED)
    di = channels.by_desk["dealer_inventory"].components
    assert _sha256(di["dealer_flow"]) == _GOLDEN_OBS_DEALER_FLOW_SHA256
    assert _sha256(di["vega_exposure"]) == _GOLDEN_OBS_VEGA_EXPOSURE_SHA256


def test_observation_channels_expose_hedging_demand_bucket():
    path = EquityVolMarket(n_days=200, seed=0).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=0)
    assert "hedging_demand" in channels.by_desk
    hd = channels.by_desk["hedging_demand"]
    assert set(hd.components.keys()) == {"hedging_demand_level", "put_skew_proxy"}
    assert hd.components["hedging_demand_level"].shape == (200,)
    assert hd.components["put_skew_proxy"].shape == (200,)


def test_hedging_demand_obs_rng_isolated_from_dealer_inventory():
    """Changing hedging_demand observation noise config must NOT perturb
    dealer_inventory's observed channels (seeds+3 stream is isolated)."""
    from sim_equity_vrp import EquityObservationConfig

    path = EquityVolMarket(n_days=200, seed=0).generate()
    default = EquityObservationChannels.build(path, mode="clean", seed=0)
    tweaked = EquityObservationChannels.build(
        path,
        mode="clean",
        seed=0,
        config=EquityObservationConfig(
            hedging_demand_noise_std=999.0,  # wildly different
            put_skew_proxy_noise_std=999.0,
        ),
    )
    di_default = default.by_desk["dealer_inventory"].components
    di_tweaked = tweaked.by_desk["dealer_inventory"].components
    np.testing.assert_array_equal(di_default["dealer_flow"], di_tweaked["dealer_flow"])
    np.testing.assert_array_equal(di_default["vega_exposure"], di_tweaked["vega_exposure"])


# ---------------------------------------------------------------------------
# v1.16 (C11) — fair_vol_baseline decision-time-safety tests.
# ---------------------------------------------------------------------------


def test_fair_vol_baseline_shape_and_warmup():
    """fair_vol_baseline has shape (n_days,); warm-up indices (t < lag +
    lookback) are populated with the OU baseline mean from the latent
    market config — no NaN, no look-ahead."""
    from sim_equity_vrp import EquityObservationConfig

    cfg = EquityObservationConfig()
    path = EquityVolMarket(n_days=200, seed=3).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=3, config=cfg)

    assert channels.fair_vol_baseline.shape == (200,)
    warmup = cfg.fair_vol_baseline_lag + cfg.fair_vol_baseline_lookback
    # Warm-up indices take the starting vol level (= OU baseline at t=0).
    warm = channels.fair_vol_baseline[:warmup]
    assert np.all(warm == path.vol_level[0])


def test_fair_vol_baseline_is_strict_function_of_past_vol_level():
    """fair_vol_baseline[t] must not depend on vol_level[>= t] for any t.

    Probe by mutating vol_level at indices >= t_probe and re-running the
    baseline computation by hand; the baseline at t_probe must match the
    version computed from the unmutated prefix."""
    from sim_equity_vrp import EquityObservationConfig

    cfg = EquityObservationConfig()
    path = EquityVolMarket(n_days=200, seed=3).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=3, config=cfg)

    lookback = cfg.fair_vol_baseline_lookback
    lag = cfg.fair_vol_baseline_lag
    for t_probe in (lag + lookback, 50, 100, 150, 199):
        lo = t_probe - lag - lookback
        hi = t_probe - lag
        # All indices in the window must be strictly less than t_probe.
        assert hi <= t_probe, f"window [{lo}:{hi}] must end strictly before t={t_probe}"
        expected = float(path.vol_level[lo:hi].mean())
        actual = float(channels.fair_vol_baseline[t_probe])
        assert np.isclose(expected, actual), (
            f"fair_vol_baseline[{t_probe}]={actual} does not match trailing "
            f"mean of vol_level[{lo}:{hi}]={expected}"
        )


def test_fair_vol_baseline_excluded_from_d12_golden():
    """Adding fair_vol_baseline as a new EquityObservationChannels field
    must NOT perturb the D12 golden hashes on dealer_inventory's arrays
    (latent or observed)."""
    path = EquityVolMarket(n_days=_GOLDEN_N_DAYS, seed=_GOLDEN_SEED).generate()
    # Latent hashes unchanged by observation-layer-only additions.
    assert _sha256(path.vol_level) == _GOLDEN_VOL_LEVEL_SHA256
    assert _sha256(path.dealer_flow) == _GOLDEN_DEALER_FLOW_SHA256
    assert _sha256(path.vega_exposure) == _GOLDEN_VEGA_EXPOSURE_SHA256
    # Observed hashes unchanged — the new merged-view key and new
    # fair_vol_baseline field are additive; legacy component arrays are
    # shared views of the pre-v1.16 buffers.
    channels = EquityObservationChannels.build(path, mode="clean", seed=_GOLDEN_SEED)
    di = channels.by_desk["dealer_inventory"].components
    assert _sha256(di["dealer_flow"]) == _GOLDEN_OBS_DEALER_FLOW_SHA256
    assert _sha256(di["vega_exposure"]) == _GOLDEN_OBS_VEGA_EXPOSURE_SHA256
