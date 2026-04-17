"""Grading harness (spec §4.7 matching + Grade emission)."""

from __future__ import annotations

from .match import DEFAULT_CLOCK_TOLERANCE, grade, grade_pairs, matches

__all__ = ["DEFAULT_CLOCK_TOLERANCE", "grade", "grade_pairs", "matches"]
