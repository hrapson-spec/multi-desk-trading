"""Demand desk — Week 1-2 stub implementation."""

from __future__ import annotations

from desks.base import StubDesk


class DemandDesk(StubDesk):
    name: str = "demand"
    spec_path: str = "desks/demand/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7
