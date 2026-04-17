"""Supply desk — Week 1-2 stub implementation.

Emits a null-signal Forecast for WTI front-month close conditioned on supply
shocks. Full implementation (Bayesian SVAR + MOIRAI-2 + CatBoost) is Phase 1
Week 5-10 per plan §12.1.
"""

from __future__ import annotations

from desks.base import StubDesk


class SupplyDesk(StubDesk):
    name: str = "supply"
    spec_path: str = "desks/supply/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7
