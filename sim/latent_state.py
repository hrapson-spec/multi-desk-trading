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
    """Per-run config for the 5-factor simulator. All values annualised."""

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

        log_price = chi + xi + c.balance_loading_gamma * (supply - demand)
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
            regimes=regimes,
            config=self.config,
        )
