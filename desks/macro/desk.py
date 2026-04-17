"""Macro & Numeraire desk — Week 1-2 stub implementation.

Deepens Week 5 per plan §12.1 (lowest architectural risk; classical
econometric stack). Month-5 checkpoint for Phase 2 equity-VRP readiness
(spec §14.7).
"""

from __future__ import annotations

from desks.base import StubDesk


class MacroDesk(StubDesk):
    name: str = "macro"
    spec_path: str = "desks/macro/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7
