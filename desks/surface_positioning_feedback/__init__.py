"""Merged equity-VRP surface-positioning-feedback desk (v1.16 restructure).

Absorbs the pre-v1.16 `dealer_inventory` + `hedging_demand` desks under the
no-signed-flow constraint per `docs/first_principles_redesign.md`. Emits
`VIX_30D_FORWARD_3D_DELTA` — a signed 3-day vol delta — so the Controller's
raw-sum aggregation at `controller/decision.py:94-112` stays unit-consistent
within the equity family.
"""

from __future__ import annotations

from .classical import ClassicalSurfacePositioningFeedbackModel
from .desk import SurfacePositioningFeedbackDesk

__all__ = [
    "ClassicalSurfacePositioningFeedbackModel",
    "SurfacePositioningFeedbackDesk",
]
