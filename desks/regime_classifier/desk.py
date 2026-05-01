"""Regime classifier stub used for early-phase hot-swap / cold-start tests.

Always emits regime_boot (P=1.0). Exercises §14.8 cold-start path.
The shipped data-driven classifier now lives in
`desks.regime_classifier.classical.HMMRegimeClassifier`; this stub
remains the trivial swap target required by Gate 3.
"""

from __future__ import annotations

from desks.base import StubClassifier


class RegimeClassifierStub(StubClassifier):
    name: str = "regime_classifier"
    spec_path: str = "desks/regime_classifier/spec.md"
