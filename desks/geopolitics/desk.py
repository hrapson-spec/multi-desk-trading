"""Geopolitics & Risk desk — Week 1-2 stub implementation.

Deepens Week 4 per plan §12.1 (stress-tests LLM two-tier routing and
structured-output validation).
"""

from __future__ import annotations

from desks.base import StubDesk


class GeopoliticsDesk(StubDesk):
    name: str = "geopolitics"
    spec_path: str = "desks/geopolitics/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7
