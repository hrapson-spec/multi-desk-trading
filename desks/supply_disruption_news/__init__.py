"""Merged oil supply-news desk (v1.16 restructure).

Absorbs the pre-v1.16 `supply` + `geopolitics` + untracked `planned_supply_balance`
+ `disruption_risk` WIP artefacts. Event-hurdle framing: activation probability
times conditional effect size. Emits `WTI_FRONT_1W_LOG_RETURN`.
"""

from __future__ import annotations

from .classical import ClassicalSupplyDisruptionNewsModel
from .desk import SupplyDisruptionNewsDesk

__all__ = ["ClassicalSupplyDisruptionNewsModel", "SupplyDisruptionNewsDesk"]
