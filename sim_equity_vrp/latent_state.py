"""Equity-vol latent state (Phase 2 MVP).

3-factor model mirroring the oil sim's pattern but scoped to vol:

  v_t : vol level. OU process around a regime-dependent mean.
  f_t : dealer_flow (AR(1)). Correlated with NEXT-period vol shocks
        — gives a dealer_inventory desk something to forecast off.
  p_t : spot log-price. Simple random walk; not the target variable
        (VIX_30D_FORWARD is). Included only to make the
        ObservationChannels.market_price surface consistent with the
        oil shape so downstream code (baselines, LODO etc.) has the
        field it expects.

The 30-day forward vol target — derivable from v_t via simple
forecasting — is what dealer_inventory tries to predict.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .regimes import (
    VolRegimeConfig,
    VolRegimeSequence,
    sample_vol_regime_sequence,
)


@dataclass(frozen=True)
class EquityVolMarketConfig:
    """Vol dynamics + dealer-flow correlation knobs."""

    # Baseline OU vol mean (annualised, percentage points). ~20 is typical VIX.
    vol_mean_baseline: float = 20.0
    # OU mean-reversion speed per day.
    vol_kappa: float = 0.05
    # Baseline vol-of-vol (daily std of OU shocks, pts).
    vol_of_vol_baseline: float = 0.8
    # Dealer-flow AR(1) coef.
    flow_ar1: float = 0.85
    # Dealer-flow std (stationary ~ 1 after warm-up).
    flow_shock_std: float = 0.5
    # Correlation of dealer_flow innovation with NEXT-step vol shock.
    # Positive: dealer gets long when vol about to rise → predictive.
    flow_vol_corr: float = 0.35
    # Spot log-price random walk step std.
    spot_step_std: float = 0.01


def phase2_mvp_config() -> EquityVolMarketConfig:
    """Pinned config for the Phase 2 MVP tests; tweaking this is a
    capability-claim debit (it would change the data fixtures downstream
    tests fit against)."""
    return EquityVolMarketConfig()


@dataclass(frozen=True)
class EquityVolPath:
    """Realised 3-factor latent state + regime sequence."""

    n_days: int
    vol_level: np.ndarray  # shape (n_days,)
    dealer_flow: np.ndarray  # shape (n_days,)
    vega_exposure: np.ndarray  # shape (n_days,) — derived from dealer_flow × vol
    spot_log_price: np.ndarray  # shape (n_days,)
    regimes: VolRegimeSequence


@dataclass
class EquityVolMarket:
    """Seed-deterministic generator for an EquityVolPath."""

    n_days: int = 1200
    seed: int = 0
    config: EquityVolMarketConfig = field(default_factory=phase2_mvp_config)
    regime_config: VolRegimeConfig = field(default_factory=VolRegimeConfig)

    def generate(self) -> EquityVolPath:
        rng = np.random.default_rng(self.seed)
        regimes = sample_vol_regime_sequence(
            n_days=self.n_days, config=self.regime_config, seed=self.seed + 1
        )

        cfg = self.config
        vol = np.empty(self.n_days, dtype=np.float64)
        flow = np.empty(self.n_days, dtype=np.float64)
        vol[0] = cfg.vol_mean_baseline
        flow[0] = 0.0

        # Pre-draw correlated innovations so the flow leads vol by one
        # step (flow[t] correlates with vol[t+1] shock).
        cov = np.array(
            [
                [1.0, cfg.flow_vol_corr],
                [cfg.flow_vol_corr, 1.0],
            ]
        )
        # Cholesky factor for 2-dim correlated normals.
        lchol = np.linalg.cholesky(cov)
        uncorrelated = rng.standard_normal((self.n_days, 2))
        correlated = uncorrelated @ lchol.T
        flow_shocks = correlated[:, 0] * cfg.flow_shock_std
        vol_shocks_unscaled = correlated[:, 1]

        for t in range(1, self.n_days):
            regime = regimes.regime_at(t)
            mean_scale = self.regime_config.vol_scaling.get((regime, "vol_mean"), 1.0)
            vov_scale = self.regime_config.vol_scaling.get((regime, "vol_of_vol"), 1.0)
            regime_mean = cfg.vol_mean_baseline * mean_scale
            regime_vov = cfg.vol_of_vol_baseline * vov_scale

            # Use the PREVIOUS step's flow-correlated shock for vol
            # → dealer_flow at t-1 predicts vol move at t.
            vol_innov = vol_shocks_unscaled[t - 1] * regime_vov
            vol[t] = vol[t - 1] + cfg.vol_kappa * (regime_mean - vol[t - 1]) + vol_innov
            # Clip to stay positive — real vol is bounded below by 0.
            vol[t] = max(vol[t], 1.0)

            flow[t] = cfg.flow_ar1 * flow[t - 1] + flow_shocks[t]

        # Derived signal: vega_exposure ≈ dealer_flow × vol_level
        vega_exposure = flow * vol

        # Spot log-price: independent RW (unused by dealer_inventory).
        spot_shocks = rng.standard_normal(self.n_days) * cfg.spot_step_std
        spot_log_price = np.cumsum(spot_shocks)

        return EquityVolPath(
            n_days=self.n_days,
            vol_level=vol,
            dealer_flow=flow,
            vega_exposure=vega_exposure,
            spot_log_price=spot_log_price,
            regimes=regimes,
        )
