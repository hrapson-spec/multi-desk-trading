"""Demand desk (Phase 1 desk 2 per spec §5.3).

Classical-specialist ridge model (plan §A Phase A) lives in classical.py.
"""

from __future__ import annotations

from .classical import ClassicalDemandModel
from .desk import DemandDesk

__all__ = ["ClassicalDemandModel", "DemandDesk"]
