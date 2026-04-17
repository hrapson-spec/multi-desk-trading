"""5-factor latent state SDE for the synthetic oil market (plan §A).

Factors (indexed by name in `LatentPath`):

  - **chi** `χ_t`: short-term deviation from long-run equilibrium
    (Schwartz-Smith short factor). Mean-reverting OU process.
  - **xi** `ξ_t`: long-run log-equilibrium level (Schwartz-Smith long
    factor). Brownian motion with drift.
  - **supply** `s_t`: supply state (units of balance), OU process around a
    regime-dependent mean.
  - **demand** `d_t`: demand state, OU process mirroring supply.
  - **events**: Hawkes self-exciting point process. Arrivals perturb
    supply / demand / short-term vol — NOT a free-floating price jump
    (user research Q1).

Observable log-price (units of dollars/barrel):
    log_price[t] = χ_t + ξ_t + γ · (s_t − d_t)

where `γ` is the inventory-balance loading. Fundamentals flow through via
the balance channel, not directly onto price.

Discretisation: explicit Euler with dt = 1/252 (trading days per year).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .regimes import (
    Regime,
    RegimeConfig,
    RegimeSequence,
    regime_scaling,
    sample_regime_sequence,
)

DT = 1.0 / 252.0  # trading-day timestep


@dataclass(frozen=True)
class LatentMarketConfig:
    """Per-run config for the 5-factor simulator. All values annualised.

    **Two structural layers** (plan §A):
      1. Schwartz-Smith + OU fundamentals (chi, xi, supply, demand) +
         Hawkes events. These provide the realistic regime-scaled
         macroeconomic dynamics that make the simulator plausible as an
         oil-market testbed.
      2. **Per-desk AR(1) return drivers** — one AR(1) process per desk
         that adds directly to log-return. Each desk observes its own
         driver in its channel, so ridge models have a clean,
         predictable signal to learn. Regime scaling amplifies the
         dominant desk's driver in each regime (e.g. supply_dominated ⇒
         supply_ar1 vol ×2.5), which is what makes regime-conditional
         Shapley differentiation measurable.

    Without layer 2, ridge-on-4-features against OU-only fundamentals
    has empirically worse-than-random-walk RMSE (noise dominates
    mean-reversion signal). Layer 2 is scoped to the Phase A
    architectural test; real-data Phase 2+ uses realistic
    signal-to-noise ratios and different fitting techniques.
    """

    # Schwartz-Smith short factor (χ): OU around 0
    chi_kappa: float = 2.0  # mean-reversion rate (half-life ≈ 0.35 yr at κ=2)
    chi_vol: float = 0.3  # annualised σ_χ

    # Schwartz-Smith long factor (ξ): GBM-like on log-price
    xi_drift: float = 0.0  # μ (annualised)
    xi_vol: float = 0.08  # σ_ξ (annualised)
    xi_initial: float = 4.382  # log(80) — baseline WTI
    chi_initial: float = 0.0

    # Supply OU
    supply_kappa: float = 1.0
    supply_vol: float = 0.2
    supply_initial: float = 0.0

    # Demand OU
    demand_kappa: float = 1.0
    demand_vol: float = 0.2
    demand_initial: float = 0.0

    # Inventory/balance loading on log-price
    balance_loading_gamma: float = 0.1

    # Hawkes event process (baseline intensity in events/year, self-excitation)
    event_mu0: float = 6.0  # expected ~6 events/year baseline
    event_alpha: float = 0.4  # self-excitation amplitude
    event_beta: float = 5.0  # decay rate
    # When an event fires, it perturbs:
    event_supply_impact: float = -0.3  # supply mean shock
    event_demand_impact: float = 0.0
    event_chi_impact: float = 0.15  # short-term vol / disruption

    # Per-desk AR(1) return drivers (layer 2). Each rho ∈ [0, 1); vol is
    # annualised. The stream is added to log-return each day and exposed
    # to the corresponding desk's channel (see sim/observations.py).
    # Default zero ⇒ disabled (pure Schwartz-Smith/OU).
    desk_ar1_rho: dict[str, float] = field(
        default_factory=lambda: {
            "storage_curve": 0.0,
            "supply": 0.0,
            "demand": 0.0,
            "geopolitics": 0.0,
            "macro": 0.0,
        }
    )
    desk_ar1_vol: dict[str, float] = field(
        default_factory=lambda: {
            "storage_curve": 0.0,
            "supply": 0.0,
            "demand": 0.0,
            "geopolitics": 0.0,
            "macro": 0.0,
        }
    )

    # Correlations (Brownian motions) — default independent
    # (kept minimal for interpretability; a single latent cov matrix would
    # make the factors non-identifiable from observations).


@dataclass(frozen=True)
class LatentPath:
    """Full latent state path for n_days. All arrays shape (n_days,)."""

    chi: np.ndarray
    xi: np.ndarray
    supply: np.ndarray
    demand: np.ndarray
    event_indicator: np.ndarray  # 0/1 per day
    event_intensity: np.ndarray  # λ_t per day (baseline + self-excitation)
    log_price: np.ndarray
    price: np.ndarray  # exp(log_price)
    # Per-desk AR(1) return drivers — layer 2 of the sim (see config).
    # dict[desk_name → ndarray[n_days]]. Always present; zero if disabled.
    desk_ar1: dict[str, np.ndarray]
    regimes: RegimeSequence
    config: LatentMarketConfig

    @property
    def n_days(self) -> int:
        return len(self.chi)

    @property
    def balance(self) -> np.ndarray:
        """Derived inventory/balance state = supply − demand."""
        out: np.ndarray = self.supply - self.demand
        return out


@dataclass
class LatentMarket:
    """Seed-deterministic generator for a 5-factor oil-market path.

    Usage:
        mkt = LatentMarket(n_days=500, seed=42)
        path = mkt.generate()  # LatentPath
    """

    n_days: int
    seed: int
    config: LatentMarketConfig = field(default_factory=LatentMarketConfig)
    regime_config: RegimeConfig = field(default_factory=RegimeConfig)

    def generate(self) -> LatentPath:
        if self.n_days <= 1:
            raise ValueError(f"n_days must be ≥ 2; got {self.n_days}")

        regimes = sample_regime_sequence(
            n_days=self.n_days, config=self.regime_config, seed=self.seed
        )
        # Use a separate RNG stream per factor so re-ordering factors does not
        # change any one factor's path. Stream IDs via rng.spawn(n) in NumPy
        # ≥1.25; we use legacy-friendly split by seeding distinct child states.
        parent = np.random.default_rng(self.seed + 1)
        rng_chi, rng_xi, rng_supply, rng_demand, rng_events = (
            np.random.default_rng(parent.integers(0, 2**32 - 1)) for _ in range(5)
        )

        c = self.config
        sqrt_dt = np.sqrt(DT)

        chi = np.empty(self.n_days)
        xi = np.empty(self.n_days)
        supply = np.empty(self.n_days)
        demand = np.empty(self.n_days)
        event_indicator = np.zeros(self.n_days, dtype=np.int64)
        event_intensity = np.empty(self.n_days)

        chi[0] = c.chi_initial
        xi[0] = c.xi_initial
        supply[0] = c.supply_initial
        demand[0] = c.demand_initial
        event_intensity[0] = c.event_mu0

        # Per-desk AR(1) return drivers (layer 2). One stream per desk,
        # deterministic via SeedSequence. Each desk observes its own
        # driver in its channel; log-return receives the sum. Local
        # import avoids a module-level cycle with sim.observations.
        from .observations import DESK_NAMES as _DESK_NAMES

        desk_ar1: dict[str, np.ndarray] = {d: np.zeros(self.n_days) for d in _DESK_NAMES}
        desk_ar1_rngs: dict[str, np.random.Generator] = {
            d: np.random.default_rng(np.random.SeedSequence([self.seed, 1000 + k]))
            for k, d in enumerate(_DESK_NAMES)
        }

        # Accumulate past-event contribution to intensity via recursive
        # exponential-decay update. Hawkes intensity is
        #     λ_t = μ_0 + α · Σ_{events s < t} β·exp(−β(t−s))
        # In discrete time with step DT, the running contribution
        # L_t := Σ β·exp(−β(t−s)) decays by exp(−β·DT) each step and jumps
        # by β on arrival.
        hawkes_decay = float(np.exp(-c.event_beta * DT))
        hawkes_self = 0.0

        for t in range(1, self.n_days):
            r: Regime = regimes.regime_at(t)

            # Chi: OU toward 0 with regime-scaled vol
            chi_vol_scale = regime_scaling(self.regime_config, r, "chi_vol")
            chi[t] = (
                chi[t - 1]
                - c.chi_kappa * chi[t - 1] * DT
                + c.chi_vol * chi_vol_scale * sqrt_dt * rng_chi.standard_normal()
            )

            # Per-desk AR(1) return drivers. Each is scaled by the regime-
            # dependent factor (e.g. "supply_vol" multiplier applies to the
            # supply desk's AR(1) driver in supply_dominated regime).
            for desk_name in _DESK_NAMES:
                rho = c.desk_ar1_rho.get(desk_name, 0.0)
                vol = c.desk_ar1_vol.get(desk_name, 0.0)
                if rho == 0.0 and vol == 0.0:
                    continue
                # Regime scaling lookup: reuse the same keys as the factor
                # names for convenience — e.g. supply desk's AR(1) vol is
                # scaled by "supply_vol" in supply_dominated regime.
                regime_scale_key = {
                    "storage_curve": "chi_vol",
                    "supply": "supply_vol",
                    "demand": "demand_vol",
                    "geopolitics": "event_mu0",
                    "macro": "chi_vol",
                }.get(desk_name, "chi_vol")
                vol_scale = regime_scaling(self.regime_config, r, regime_scale_key)
                desk_ar1[desk_name][t] = (
                    rho * desk_ar1[desk_name][t - 1]
                    + vol * vol_scale * sqrt_dt * desk_ar1_rngs[desk_name].standard_normal()
                )

            # Xi: drifting Brownian motion on log-price equilibrium
            xi[t] = xi[t - 1] + c.xi_drift * DT + c.xi_vol * sqrt_dt * rng_xi.standard_normal()

            # Supply: OU toward regime-dependent mean with regime-scaled vol
            supply_mean = regime_scaling(self.regime_config, r, "supply_mean", default=0.0)
            supply_vol_scale = regime_scaling(self.regime_config, r, "supply_vol")
            supply[t] = (
                supply[t - 1]
                - c.supply_kappa * (supply[t - 1] - supply_mean) * DT
                + c.supply_vol * supply_vol_scale * sqrt_dt * rng_supply.standard_normal()
            )

            # Demand: OU toward regime-dependent mean
            demand_mean = regime_scaling(self.regime_config, r, "demand_mean", default=0.0)
            demand_vol_scale = regime_scaling(self.regime_config, r, "demand_vol")
            demand[t] = (
                demand[t - 1]
                - c.demand_kappa * (demand[t - 1] - demand_mean) * DT
                + c.demand_vol * demand_vol_scale * sqrt_dt * rng_demand.standard_normal()
            )

            # Hawkes event process
            mu0_scale = regime_scaling(self.regime_config, r, "event_mu0")
            lam = c.event_mu0 * mu0_scale + c.event_alpha * hawkes_self
            event_intensity[t] = lam
            # Bernoulli approximation: P(event in [t, t+DT]) = 1 - exp(-λ·DT)
            p_event = 1.0 - float(np.exp(-lam * DT))
            fired = int(rng_events.random() < p_event)
            event_indicator[t] = fired
            hawkes_self = hawkes_self * hawkes_decay + c.event_beta * fired

            # Event impact applied this same step — events perturb states,
            # not price directly (user research Q1).
            if fired:
                supply[t] += c.event_supply_impact * sqrt_dt
                demand[t] += c.event_demand_impact * sqrt_dt
                chi[t] += c.event_chi_impact * sqrt_dt

        # Log-price = Schwartz-Smith + OU fundamentals + cumulative sum of
        # all per-desk AR(1) return drivers. The desk AR(1) streams are
        # *returns* not levels, so we accumulate them.
        ar1_sum_returns = np.zeros(self.n_days)
        for desk_name in _DESK_NAMES:
            ar1_sum_returns += desk_ar1[desk_name]
        ar1_log_price_component = np.cumsum(ar1_sum_returns)

        log_price = chi + xi + c.balance_loading_gamma * (supply - demand) + ar1_log_price_component
        price = np.exp(log_price)

        return LatentPath(
            chi=chi,
            xi=xi,
            supply=supply,
            demand=demand,
            event_indicator=event_indicator,
            event_intensity=event_intensity,
            log_price=log_price,
            price=price,
            desk_ar1=desk_ar1,
            regimes=regimes,
            config=self.config,
        )


def phase_a_config() -> LatentMarketConfig:
    """High-signal config for the Phase A integration test (plan §A).

    The default LatentMarketConfig is calibrated to plausible real-oil-market
    annualised statistics, which produces a signal-to-noise ratio too low
    for a 4-feature ridge to beat random-walk RMSE on ~200-day held-out
    data. Phase A is an architectural test, not an alpha test; we boost
    the predictable components:

      - chi_kappa = 12 (short-term reversion, ~3-week half-life — stronger
        reversion means "chi returns to 0" is a more useful prediction
        over the 3-day horizon).
      - chi_vol = 1.0 annualised (chi amplitude ±0.25 typical).
      - supply/demand_kappa = 5.0 (faster OU reversion).
      - balance_loading_gamma = 0.6 (supply/demand shocks move price
        meaningfully).
      - event impacts doubled so geopolitics differentiates from macro
        in event regimes.

    Production-calibrated values (real-data Phase 2+) will differ; this
    config is scoped to the Phase A asserted-capability test.
    """
    # Phase A: dominant-signal AR(1) drivers per desk, with the OU
    # fundamental layer effectively turned off so the test isolates the
    # architecture (Controller + LODO + Shapley + weight promotion) from
    # the question "does ridge-on-4-features have alpha on a multi-factor
    # oil market?". The OU fundamentals are always there as architectural
    # flavouring but the predictable variance comes from the AR(1) drivers.
    #
    # Vols are chosen so (a) each desk's ridge can learn its own AR(1)
    # well enough to beat random-walk RMSE on a held-out split and (b) the
    # cumulative sum of returns doesn't drift log-price catastrophically
    # over 500 days.
    rho = 0.95
    vol = 0.04
    return LatentMarketConfig(
        # Baseline fundamentals: very low vol so AR(1) drivers dominate.
        chi_kappa=2.0,
        chi_vol=0.02,
        xi_drift=0.0,
        xi_vol=0.01,
        supply_kappa=4.0,
        supply_vol=0.05,
        demand_kappa=4.0,
        demand_vol=0.05,
        balance_loading_gamma=0.05,
        event_supply_impact=-0.05,
        event_chi_impact=0.03,
        # Per-desk AR(1) drivers — dominant signal source.
        desk_ar1_rho={
            "storage_curve": rho,
            "supply": rho,
            "demand": rho,
            "geopolitics": rho,
            "macro": rho,
        },
        desk_ar1_vol={
            "storage_curve": vol,
            "supply": vol,
            "demand": vol,
            "geopolitics": vol,
            "macro": vol,
        },
    )
