"""Gate evaluation harness (spec §7.1).

Every desk's promotion path runs through the three hard gates:
  Gate 1 — skill vs pre-registered naive baseline
  Gate 2 — dev→test sign preservation (Kronos-RCA gate)
  Gate 3 — hot-swap against stub without breaking the Controller

This package provides reusable implementations so each desk's deepening
uses the same gate logic. LODO diagnostic is computed alongside but is
not a hard gate by default (§7.2).
"""

from __future__ import annotations

from .gates import (
    GateReport,
    GateResult,
    gate_hot_swap,
    gate_sign_preservation,
    gate_skill_vs_baseline,
)
from .runner import GateRunner

__all__ = [
    "GateReport",
    "GateResult",
    "GateRunner",
    "gate_hot_swap",
    "gate_sign_preservation",
    "gate_skill_vs_baseline",
]
