"""Equity-vol latent state (Phase 2, v1.13 = 4-factor).

4-factor model mirroring the oil sim's pattern but scoped to vol:

  v_t   : vol level. OU process around a regime-dependent mean.
  f_t   : dealer_flow (AR(1)). Correlated with next-period vol shocks
          — feeds the dealer_inventory desk (MVP).
  hd_t  : hedging_demand (AR(1)). Correlated with next-period vol
          shocks — feeds the hedging_demand desk (v1.13). Separate
          signal stream from dealer_flow by domain design.
  p_t   : spot log-price. Simple random walk; not the target variable
          (VIX_30D_FORWARD is). Kept so market_price surface parity
          with oil holds.

Derived signals:
  vega_exposure  = dealer_flow × vol_level  (serves dealer_inventory)
  put_skew_proxy = hedging_demand × vol_level  (serves hedging_demand;
                  NOT clipped to positive — real put skew is ≥ 0 but
                  this proxy is signed by construction. See spec.md.)

Seed-offset convention (v1.13):
  seed       — main RNG stream (dealer_flow + vol + spot). Load-bearing
               for dealer_inventory determinism — MUST NOT CHANGE.
  seed + 1   — regime sequence (existing).
  seed + 2   — hedging_demand latent shocks (new, v1.13).
  seed + 3   — hedging_demand observation noise (in observations.py).
All offsets are 32-bit masked to avoid any future overflow concerns.

The first ~20 indices are burn-in (hd[0] = 0 forces put_skew_proxy[0]
= 0 regardless of vol); downstream tests skip `[:20]` or pick indices
well past the warm-up.
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
    # hedging_demand (v1.13) — institutional put-buying pressure.
    hd_ar1: float = 0.90
    # Stationary std of hedging_demand ≈ hd_shock_std / sqrt(1 − hd_ar1²) ≈ 0.92.
    hd_shock_std: float = 0.4
    # Correlation of hedging_demand innovation with next-step vol shock.
    # Stronger than flow_vol_corr because hedging demand is a direct
    # IV-pressure signal, whereas dealer flow is a derived secondary signal.
    hd_vol_corr: float = 0.55
    hd_init_value: float = 0.0
    # v1.16 (X1) — earnings-event channel. Events at time t are correlated
    # with vol_shocks_unscaled at t + earnings_vol_lead, so the observable
    # earnings cluster size at t predicts vol_level[t + earnings_vol_lead + 1].
    # Default lead=2 → earnings predict vol 3 days out, matching the
    # earnings_calendar desk horizon.
    earnings_vol_corr: float = 0.45
    earnings_vol_lead: int = 2
    # Threshold on the unit-variance earnings score. 1.2 → P(event) ≈ 11.5%.
    earnings_event_threshold: float = 1.2
    # Rolling cluster-size window (looks backward only — observation-safe).
    earnings_cluster_window: int = 5


def phase2_mvp_config() -> EquityVolMarketConfig:
    """Pinned config for the Phase 2 MVP tests; tweaking this is a
    capability-claim debit (it would change the data fixtures downstream
    tests fit against)."""
    return EquityVolMarketConfig()


@dataclass(frozen=True)
class EquityVolPath:
    """Realised 4-factor latent state + v1.13 hd channels + v1.16 earnings channel."""

    n_days: int
    vol_level: np.ndarray  # shape (n_days,)
    dealer_flow: np.ndarray  # shape (n_days,)
    vega_exposure: np.ndarray  # shape (n_days,) — derived from dealer_flow × vol
    spot_log_price: np.ndarray  # shape (n_days,)
    hedging_demand: np.ndarray  # shape (n_days,) — v1.13
    put_skew_proxy: np.ndarray  # shape (n_days,) — derived from hedging_demand × vol, v1.13
    regimes: VolRegimeSequence
    # v1.16 (X1) — earnings event channel, generated AFTER all existing
    # draws so D12 golden hashes on the arrays above stay byte-identical.
    # Isolated RNG stream at seed+4 (main=seed, regimes=seed+1, hd_latent=seed+2,
    # hd_obs=seed+3, earnings=seed+4).
    earnings_event_indicator: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.int8)
    )
    earnings_cluster_size: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.int16)
    )


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
        # IMPORTANT: must be drawn BEFORE any v1.13 additions to preserve
        # the pre-v1.13 main-rng stream state — dealer_inventory golden
        # fixtures depend on this ordering.
        spot_shocks = rng.standard_normal(self.n_days) * cfg.spot_step_std
        spot_log_price = np.cumsum(spot_shocks)

        # --- v1.13: hedging_demand (isolated RNG stream, seed+2) ---
        # Correlation is embedded via `hd_shocks_unit = r * vol_shocks_unscaled
        # + sqrt(1 - r²) * hd_noise`. Valid because `vol_shocks_unscaled` has
        # unit variance by construction (Cholesky of the 2x2 flow-vol cov with
        # unit diagonal yields a unit-variance second column).
        hd_rng = np.random.default_rng((self.seed + 2) & 0xFFFFFFFF)
        hd_noise = hd_rng.standard_normal(self.n_days)
        r = cfg.hd_vol_corr
        hd_shocks_unit = r * vol_shocks_unscaled + np.sqrt(1.0 - r * r) * hd_noise
        hedging_demand = np.empty(self.n_days, dtype=np.float64)
        hedging_demand[0] = cfg.hd_init_value
        for t in range(1, self.n_days):
            hedging_demand[t] = (
                cfg.hd_ar1 * hedging_demand[t - 1] + cfg.hd_shock_std * hd_shocks_unit[t]
            )
        # Derived: put_skew_proxy = hedging_demand × vol_level. Signed by
        # construction (unlike real-world put skew which is strictly ≥ 0).
        put_skew_proxy = hedging_demand * vol

        # --- v1.16 (X1): earnings-event channel ---
        # Generated AFTER all existing draws so vol_level / dealer_flow /
        # vega_exposure / spot_log_price / hedging_demand / put_skew_proxy
        # bytes are unchanged (D12 golden fixtures preserved). Isolated
        # RNG stream at seed+4 does not interfere with the main, +1, +2,
        # +3 streams.
        #
        # Forward correlation: earnings_score[t] correlates with
        # vol_shocks_unscaled[t + lead]. Since vol_shocks_unscaled[k] drives
        # vol_level[k+1], observing earnings[t] gives a leading signal on
        # vol_level[t + lead + 1]. Default lead=2 → earnings[t] predicts
        # vol_level[t+3], matching the earnings_calendar desk horizon.
        earnings_rng = np.random.default_rng((self.seed + 4) & 0xFFFFFFFF)
        earnings_noise = earnings_rng.standard_normal(self.n_days)
        lead = cfg.earnings_vol_lead
        r_e = cfg.earnings_vol_corr
        earnings_score = np.empty(self.n_days, dtype=np.float64)
        if self.n_days > lead:
            # For t in [0, n_days - lead), use vol_shocks_unscaled[t + lead].
            earnings_score[:-lead] = (
                r_e * vol_shocks_unscaled[lead:]
                + np.sqrt(1.0 - r_e * r_e) * earnings_noise[:-lead]
            )
            # Tail fallback: no future vol available → pure noise.
            earnings_score[-lead:] = earnings_noise[-lead:]
        else:
            earnings_score = earnings_noise

        earnings_event_indicator = (earnings_score > cfg.earnings_event_threshold).astype(
            np.int8
        )
        window = cfg.earnings_cluster_window
        earnings_cluster_size = np.zeros(self.n_days, dtype=np.int16)
        for t in range(self.n_days):
            lo = max(0, t - window + 1)
            earnings_cluster_size[t] = int(earnings_event_indicator[lo : t + 1].sum())

        return EquityVolPath(
            n_days=self.n_days,
            vol_level=vol,
            dealer_flow=flow,
            vega_exposure=vega_exposure,
            spot_log_price=spot_log_price,
            hedging_demand=hedging_demand,
            put_skew_proxy=put_skew_proxy,
            regimes=regimes,
            earnings_event_indicator=earnings_event_indicator,
            earnings_cluster_size=earnings_cluster_size,
        )
