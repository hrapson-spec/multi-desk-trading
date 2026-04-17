"""Regime classifier — Week 1-2 stub implementation.

Always emits regime_boot (P=1.0). Exercises §14.8 cold-start path.
Full HDP-HMM implementation deferred to last step of Phase 1 per §12.1
('Controller weight matrix — final step') since the classifier's inputs
are the mature desk outputs.
"""

from __future__ import annotations

from desks.base import StubClassifier


class RegimeClassifierStub(StubClassifier):
    name: str = "regime_classifier"
    spec_path: str = "desks/regime_classifier/spec.md"
