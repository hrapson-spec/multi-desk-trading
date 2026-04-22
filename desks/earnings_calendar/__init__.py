"""Equity-VRP earnings-calendar desk (v1.16 W10 skeleton).

Event-driven vol-expansion desk per `docs/first_principles_redesign.md`
(pasted review explicitly keeps earnings_calendar separate from
surface_positioning_feedback). W10 ships a structurally-complete desk
that passes Gate 3 hot-swap and composes with surface_positioning_feedback
under `controller/decision.py:94-112` raw-sum aggregation (both emit
VIX_30D_FORWARD_3D_DELTA).

Gate 1/2 performance is expected weak at W10 because the sim has no
earnings-event channel yet. Full mechanism rebuild (structured event
schema + impact model + earnings channel in sim_equity_vrp) is a
follow-on wave per the commission at
docs/pm/earnings_calendar_engineering_commission.md.
"""

from __future__ import annotations

from .classical import ClassicalEarningsCalendarModel
from .desk import EarningsCalendarDesk

__all__ = ["ClassicalEarningsCalendarModel", "EarningsCalendarDesk"]
