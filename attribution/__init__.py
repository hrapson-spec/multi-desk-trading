"""LODO and Shapley attribution (spec §9).

LODO and Shapley are **co-primary** (§9.3) — they answer different questions:
  - LODO: "if this desk were gone, would the Controller be better or worse?"
  - Shapley: "how much of the signal actually came from this desk, net of
    correlation with other desks?"

Phase 1 ships LODO first (signal-space delta at decision time); Shapley
and grading-space LODO follow in subsequent commits.
"""

from __future__ import annotations

from .lodo import (
    LODO_METRIC_POSITION_SIZE_DELTA,
    compute_lodo_signal_space,
    persist_lodo_rows,
)

__all__ = [
    "LODO_METRIC_POSITION_SIZE_DELTA",
    "compute_lodo_signal_space",
    "persist_lodo_rows",
]
