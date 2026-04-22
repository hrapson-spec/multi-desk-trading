"""Classical model for the merged oil demand-nowcast desk (v1.16).

Ridge-level head acceptable for Phase 2 scale-out per the commission at
`docs/pm/oil_demand_nowcast_engineering_commission.md`. Full mixed-frequency
state-space / dynamic-factor nowcast is a §7.3 escalation under D1.

Inherits from the legacy `ClassicalDemandModel` for C5a (additive). C12 cleanup
inlines the base-class implementation when `desks/demand/` is deleted.
"""

from __future__ import annotations

from dataclasses import dataclass

from desks.demand.classical import ClassicalDemandModel


@dataclass
class ClassicalOilDemandNowcastModel(ClassicalDemandModel):
    horizon_days: int = 7


__all__ = ["ClassicalOilDemandNowcastModel"]
