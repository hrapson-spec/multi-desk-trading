"""Dealer-inventory desk — equity-VRP Phase 2 MVP analogue to the
oil storage_curve desk (spec v1.12).

Load-bearing role: prove the architecture redeploys to equity-VRP
with zero changes to shared infrastructure. This is the single desk
shipped in the Phase 2 MVP; the other four equity-VRP desks
(hedging_demand, term_structure, earnings_calendar, macro_regime)
follow in Phase 2 scale-out.
"""

from __future__ import annotations

from .classical import ClassicalDealerInventoryModel
from .desk import DealerInventoryDesk

__all__ = [
    "ClassicalDealerInventoryModel",
    "DealerInventoryDesk",
]
