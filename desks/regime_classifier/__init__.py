"""Regime classifier (Phase 1 desk 6 per spec §5.3).

Domain-blind: consumes desk output Forecasts, emits RegimeLabel events.
Under equity-VRP redeployment (§8.4, §14.7), this desk redeploys with zero
code changes (retrained on equity-VRP desk outputs).

Phase A uses a ground-truth pass-through classifier (see classical.py)
to isolate desk-architecture testing from classifier-quality testing.
A real HMM/HDP-HMM is a v0.2 follow-up.
"""

from __future__ import annotations

from .classical import GroundTruthRegimeClassifier, HMMRegimeClassifier
from .desk import RegimeClassifierStub

__all__ = [
    "GroundTruthRegimeClassifier",
    "HMMRegimeClassifier",
    "RegimeClassifierStub",
]
