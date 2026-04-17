"""Synthetic shared-latent oil market simulator (plan §A).

The package generates a 5-factor latent state path, a regime-tagged
episode sequence, and per-desk observation channels for the Phase A/B/C
multi-desk integration tests.

Design choices locked from user research (Q1–Q3):

  - **5 latent processes** (Schwartz-Smith short + long, supply OU, demand
    OU, Hawkes event process). Merging supply + demand would make the
    simulator simpler than the 5-desk architecture it is meant to validate.
  - **Events perturb other states**, not price directly. Hawkes arrivals
    shift supply / demand / risk-sentiment; price responds via the price
    formula, not a free-floating jump.
  - **Regime-tagged episodes** so different desks dominate in different
    regimes — the Controller's regime-conditional weight matrix (§8.2) has
    something to switch on.
  - **Staged observability**: `ObservationChannels(mode="clean"|"leakage"
    |"realistic")`. Phase A ships clean; Phase B adds leakage; Phase C adds
    regime-dependent contamination + chatter + missingness + lag.
"""

from __future__ import annotations

from .latent_state import LatentMarket, LatentMarketConfig, LatentPath
from .observations import ObservationChannels, ObservationConfig
from .regimes import Regime, RegimeConfig, RegimeSequence

__all__ = [
    "LatentMarket",
    "LatentMarketConfig",
    "LatentPath",
    "ObservationChannels",
    "ObservationConfig",
    "Regime",
    "RegimeConfig",
    "RegimeSequence",
]
