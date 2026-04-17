"""Supply desk (Phase 1 desk 1 per spec §5.3).

Classical-specialist ridge model (plan §A Phase A) lives in classical.py;
Bayesian SVAR + MOIRAI-2 real-data escalation is a v0.2+ follow-up.
"""

from __future__ import annotations

from .classical import ClassicalSupplyModel
from .desk import SupplyDesk

__all__ = ["ClassicalSupplyModel", "SupplyDesk"]
