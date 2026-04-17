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
    LODO_METRIC_SQUARED_ERROR_DELTA,
    compute_lodo_grading_space,
    compute_lodo_signal_space,
    persist_lodo_rows,
)
from .shapley import (
    SHAPLEY_EXACT_MAX_N,
    SHAPLEY_METRIC_POSITION_SIZE_DELTA,
    compute_shapley_signal_space,
    persist_shapley_rows,
)

__all__ = [
    "LODO_METRIC_POSITION_SIZE_DELTA",
    "LODO_METRIC_SQUARED_ERROR_DELTA",
    "SHAPLEY_EXACT_MAX_N",
    "SHAPLEY_METRIC_POSITION_SIZE_DELTA",
    "compute_lodo_grading_space",
    "compute_lodo_signal_space",
    "compute_shapley_signal_space",
    "persist_lodo_rows",
    "persist_shapley_rows",
]
