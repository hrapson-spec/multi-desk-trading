"""Macro & Numeraire desk (Phase 1 desk 5 per spec §5.3).

Classical-specialist ridge model (plan §A Phase A) lives in classical.py.
BVAR / hierarchical-Bayes on real FRED data is a v0.2+ follow-up.
"""

from __future__ import annotations

from .classical import ClassicalMacroModel
from .desk import MacroDesk

__all__ = ["ClassicalMacroModel", "MacroDesk"]
