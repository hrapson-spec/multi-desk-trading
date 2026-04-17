"""Reliability-gate runner (spec §12.2 point 3, §14.9 v1.6).

Wall-clock endurance test. Designed around the five issues flagged
in the v1.5 critique:

  1. Duration calibrated to 7 days (not 28) — catches the meaningful
     failure modes without inflating the critical path.
  2. Checkpoint + auto-resume tolerates OS reboots / dep upgrades /
     laptop sleep without resetting the 7-day clock.
  3. Real-time synthetic data feed (drip-fed LatentPath) keeps the
     loop non-idle during the run.
  4. Instrumentation-heavy: ResourceMonitor writes telemetry every
     60 s so shorter runs still catch slow leaks.
  5. Pre-registered numeric thresholds replace the hand-wavy "zero
     infrastructure incidents".

Public API:
  - `ResourceMonitor`: samples RSS / FDs / DB size / elapsed / decisions
  - `CheckpointStore`: pickle save/load of runner state for resume
  - `IncidentDetector`: classifies telemetry + exceptions into
    numerically-defined incident classes
  - `SyntheticDataFeed`: drip-feeds a LatentPath at real-time cadence
  - `SoakRunner`: orchestrates the loop end-to-end
"""

from __future__ import annotations

from .checkpoint import CheckpointStore, SoakState
from .data_feed import SyntheticDataFeed
from .incident import IncidentDetector
from .monitor import ResourceMonitor
from .runner import SoakResult, SoakRunner, TickFn

__all__ = [
    "CheckpointStore",
    "IncidentDetector",
    "ResourceMonitor",
    "SoakResult",
    "SoakRunner",
    "SoakState",
    "SyntheticDataFeed",
    "TickFn",
]
