"""Regime classifier (Phase 1 desk 6 per spec §5.3).

Domain-blind: consumes desk output Forecasts, emits RegimeLabel events.
Under equity-VRP redeployment (§8.4, §14.7), this desk redeploys with zero
code changes (retrained on equity-VRP desk outputs).
"""

from __future__ import annotations

from .desk import RegimeClassifierStub

__all__ = ["RegimeClassifierStub"]
