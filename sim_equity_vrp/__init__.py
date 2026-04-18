"""Synthetic equity-volatility market simulator (spec v1.12 Phase 2 MVP).

Parallel to `sim/` (the crude-oil Phase 1 simulator). Both coexist;
shared infrastructure is domain-neutral per §8.4. This package is
explicitly domain-scoped — the Phase 2 portability test excludes it
from the "shared-infra must stay neutral" scan the same way it
excludes `sim/`.

Minimal fidelity by design: this is a test fixture proving the
portability claim, not a realistic equity-vol model. A production
equity-VRP instance would bring its own simulator (or real data).

Interface mirrors `sim/`:
  - `EquityVolMarket.generate()` → `EquityVolPath`
  - `EquityObservationChannels.build(path, mode="clean", seed=...)`
  - `VOL_REGIMES` list for the regime classifier.
Desks code is mode-agnostic; a dealer_inventory desk consumes
`channels.by_desk["dealer_inventory"].components` the same way
storage_curve consumes the oil channels.
"""

from __future__ import annotations

from .latent_state import EquityVolMarket, EquityVolMarketConfig, EquityVolPath
from .observations import EquityObservationChannels, EquityObservationConfig
from .regimes import VOL_REGIMES, VolRegime, VolRegimeConfig, VolRegimeSequence

__all__ = [
    "VOL_REGIMES",
    "EquityObservationChannels",
    "EquityObservationConfig",
    "EquityVolMarket",
    "EquityVolMarketConfig",
    "EquityVolPath",
    "VolRegime",
    "VolRegimeConfig",
    "VolRegimeSequence",
]
