"""Desks package. Each desk is a subpackage with desk.py + spec.md.

Phase 1 desks (spec §5.3):
  supply, demand, storage_curve, geopolitics, macro, regime_classifier

Importing from this package is explicitly ALLOWED from integration tests
and from the Controller's orchestration code; FORBIDDEN from
tests/test_boundary_purity.py (spec §4.5).
"""

from __future__ import annotations

from .base import ClassifierProtocol, DeskProtocol, StubClassifier, StubDesk

__all__ = ["ClassifierProtocol", "DeskProtocol", "StubClassifier", "StubDesk"]
