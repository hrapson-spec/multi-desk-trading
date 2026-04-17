"""Regime-tagged episode sequence (plan §A).

A 4-state persistent hidden Markov chain over
`{equilibrium, supply_dominated, demand_dominated, event_driven}`.
Transitions are sticky (typical dwell time 20–60 days) so the sequence
produces identifiable episodes rather than rapid regime flicker.

Each regime scales the factor dynamics in `latent_state.py` differently —
see `RegimeConfig.factor_scaling` — so the same seed can produce very
different observable paths depending on the regime sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

Regime = Literal["equilibrium", "supply_dominated", "demand_dominated", "event_driven"]

REGIMES: tuple[Regime, ...] = (
    "equilibrium",
    "supply_dominated",
    "demand_dominated",
    "event_driven",
)


@dataclass(frozen=True)
class RegimeConfig:
    """Transition matrix + per-regime factor scaling.

    transition_matrix rows sum to 1; diagonal entries are high (sticky).
    factor_scaling maps (regime, factor_name) → multiplier applied to that
    factor's volatility or mean in `latent_state.py`. Missing entries
    default to 1.0 (no scaling).
    """

    transition_matrix: np.ndarray = field(
        default_factory=lambda: np.array(
            [
                [0.97, 0.01, 0.01, 0.01],  # equilibrium sticky
                [0.02, 0.95, 0.01, 0.02],  # supply sticky
                [0.02, 0.01, 0.95, 0.02],  # demand sticky
                [0.04, 0.02, 0.02, 0.92],  # event shorter dwell (more transient)
            ]
        )
    )
    initial_distribution: np.ndarray = field(default_factory=lambda: np.array([0.4, 0.2, 0.2, 0.2]))

    # Per-regime multipliers on factor volatilities / means. Keys are
    # (regime, factor_name). Used by latent_state.py.
    factor_scaling: dict[tuple[Regime, str], float] = field(
        default_factory=lambda: {
            # Supply-dominated: supply shocks are bigger and mean shifts negative
            ("supply_dominated", "supply_vol"): 2.5,
            ("supply_dominated", "supply_mean"): -1.0,
            # Demand-dominated: demand shocks bigger, mean shifts positive
            ("demand_dominated", "demand_vol"): 2.5,
            ("demand_dominated", "demand_mean"): 1.0,
            # Event-driven: Hawkes intensity elevated + short-term vol up
            ("event_driven", "event_mu0"): 3.0,
            ("event_driven", "chi_vol"): 1.8,
            # Equilibrium: nothing scaled (all multipliers are 1.0)
        }
    )


@dataclass(frozen=True)
class RegimeSequence:
    """Sequence of length n_days with a regime label per day."""

    labels: tuple[Regime, ...]
    indices: np.ndarray  # integer index into REGIMES, shape (n_days,)

    def __len__(self) -> int:
        return len(self.labels)

    def regime_at(self, i: int) -> Regime:
        return self.labels[i]


def sample_regime_sequence(n_days: int, config: RegimeConfig, seed: int) -> RegimeSequence:
    """Sample a regime sequence of length n_days under the config.

    Determinism: identical (n_days, config, seed) ⇒ identical output.
    """
    if n_days <= 0:
        raise ValueError(f"n_days must be positive; got {n_days}")
    # Row sums must be 1 for a valid transition matrix.
    row_sums = config.transition_matrix.sum(axis=1)
    if not np.allclose(row_sums, 1.0, atol=1e-9):
        raise ValueError(f"transition_matrix rows must sum to 1; got {row_sums.tolist()}")
    if not np.isclose(config.initial_distribution.sum(), 1.0, atol=1e-9):
        raise ValueError("initial_distribution must sum to 1")

    rng = np.random.default_rng(seed)
    idx = np.empty(n_days, dtype=np.int64)
    idx[0] = int(rng.choice(len(REGIMES), p=config.initial_distribution))
    for t in range(1, n_days):
        idx[t] = int(rng.choice(len(REGIMES), p=config.transition_matrix[idx[t - 1]]))
    labels = tuple(REGIMES[i] for i in idx)
    return RegimeSequence(labels=labels, indices=idx)


def regime_scaling(
    config: RegimeConfig, regime: Regime, factor_name: str, default: float = 1.0
) -> float:
    """Look up the multiplier for (regime, factor_name); default if missing."""
    return config.factor_scaling.get((regime, factor_name), default)
