"""Equity-vol regime sequence (Phase 2 MVP).

3-state sticky Markov chain over `{vol_quiet, vol_stress,
vol_recovery}`. Transitions are sticky so episodes are long enough
to be identifiable. Regime scaling operates on vol dynamics in
`latent_state.py`.

Strings are distinct from oil's `REGIMES` (equilibrium,
supply_dominated, demand_dominated, event_driven) so the two
domains' SignalWeight / ControllerParams rows never shadow each
other even if the same DuckDB file hosted both (which no test does
today — kept separate).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

VolRegime = Literal["vol_quiet", "vol_stress", "vol_recovery"]

VOL_REGIMES: tuple[VolRegime, ...] = (
    "vol_quiet",
    "vol_stress",
    "vol_recovery",
)


@dataclass(frozen=True)
class VolRegimeConfig:
    """3x3 transition matrix + per-regime vol scaling.

    quiet: low mean vol, low vol-of-vol. Dominant (60% of days).
    stress: high mean vol, high vol-of-vol. Transient.
    recovery: elevated mean, decaying. Usually follows stress.
    """

    transition_matrix: np.ndarray = field(
        default_factory=lambda: np.array(
            [
                [0.97, 0.02, 0.01],  # quiet sticky
                [0.05, 0.90, 0.05],  # stress → usually recovery
                [0.10, 0.05, 0.85],  # recovery → usually quiet
            ]
        )
    )
    initial_distribution: np.ndarray = field(default_factory=lambda: np.array([0.6, 0.2, 0.2]))
    # Multipliers applied to vol dynamics (mean-level + vol-of-vol).
    vol_scaling: dict[tuple[VolRegime, str], float] = field(
        default_factory=lambda: {
            ("vol_stress", "vol_mean"): 3.0,
            ("vol_stress", "vol_of_vol"): 2.5,
            ("vol_recovery", "vol_mean"): 1.6,
            ("vol_recovery", "vol_of_vol"): 1.3,
            # quiet: no scaling (multipliers are 1.0 by default).
        }
    )


@dataclass(frozen=True)
class VolRegimeSequence:
    """Realised regime sequence. `regime_at(i)` returns the label."""

    labels: tuple[VolRegime, ...]
    indices: np.ndarray

    def regime_at(self, i: int) -> VolRegime:
        return self.labels[i]


def sample_vol_regime_sequence(
    *,
    n_days: int,
    config: VolRegimeConfig,
    seed: int,
) -> VolRegimeSequence:
    """Seed-deterministic sampling of the regime chain."""
    rng = np.random.default_rng(seed)
    idx = np.empty(n_days, dtype=np.int64)
    idx[0] = int(rng.choice(len(VOL_REGIMES), p=config.initial_distribution))
    for t in range(1, n_days):
        idx[t] = int(rng.choice(len(VOL_REGIMES), p=config.transition_matrix[idx[t - 1]]))
    labels = tuple(VOL_REGIMES[i] for i in idx)
    return VolRegimeSequence(labels=labels, indices=idx)
