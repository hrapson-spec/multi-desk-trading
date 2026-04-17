"""Regime-conditional, linear-sizing Controller (spec §8).

The Controller reads the latest RegimeLabel, looks up SignalWeights +
ControllerParams for that regime, and emits a Decision — a pure function
of its inputs. No online learning; all adaptation happens via discrete
weight promotions from the research loop (§8.3).

Cold-start (§14.8): on boot before any promotion, seed_cold_start writes
one uniform SignalWeight per (regime, desk, target) and one matching
ControllerParams per regime with `validation_artefact="cold_start"`.
"""

from __future__ import annotations

from .cold_start import DEFAULT_COLD_START_LIMIT, seed_cold_start
from .decision import Controller

__all__ = ["Controller", "DEFAULT_COLD_START_LIMIT", "seed_cold_start"]
