"""Classical model for the merged supply-disruption-news desk (v1.16).

Ridge-level head acceptable for Phase 2 scale-out per the v1.16 commission
(`docs/pm/supply_disruption_news_engineering_commission.md`). Mechanism rebuild
(two-stage hurdle / Bayesian event study / GBDT on structured event features) is
a §7.3 escalation item under D1.

Inherits from the legacy `ClassicalGeopoliticsModel` to keep C4a a pure desk
addition — C4b deletes `desks/geopolitics/` and moves the base-class
implementation in-place. Horizon is pinned to 7 days to match the shared oil
emission target `WTI_FRONT_1W_LOG_RETURN`.
"""

from __future__ import annotations

from dataclasses import dataclass

from desks.geopolitics.classical import ClassicalGeopoliticsModel


@dataclass
class ClassicalSupplyDisruptionNewsModel(ClassicalGeopoliticsModel):
    horizon_days: int = 7


__all__ = ["ClassicalSupplyDisruptionNewsModel"]
