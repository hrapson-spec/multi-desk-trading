"""Geopolitics & Risk desk (Phase 1 desk 4 per spec §5.3).

Classical-specialist ridge model (plan §A Phase A) lives in classical.py.
LLM-based news extraction is a v0.2+ follow-up.
"""

from __future__ import annotations

from .classical import ClassicalGeopoliticsModel
from .desk import GeopoliticsDesk

__all__ = ["ClassicalGeopoliticsModel", "GeopoliticsDesk"]
