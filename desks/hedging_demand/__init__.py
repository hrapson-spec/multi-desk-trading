"""Hedging-demand desk — equity-VRP Phase 2 scale-out (spec v1.13).

Analogue to the oil `supply` desk. Forecasts next-period vol from
institutional put-buying pressure (dealer hedging flow +
put-skew proxy).
"""

from __future__ import annotations

from .classical import ClassicalHedgingDemandModel
from .desk import HedgingDemandDesk

__all__ = [
    "ClassicalHedgingDemandModel",
    "HedgingDemandDesk",
]
