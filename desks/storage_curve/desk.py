"""Storage & Curve desk — Week 1-2 stub implementation.

First real-deepen target per plan §12.1 (highest novel-tech content: Kronos,
Dynamic Nelson-Siegel + LSTM, functional change-point, CatBoost on COT).
Earliest failure mode; most informative for TSFM validation approach.
"""

from __future__ import annotations

from desks.base import StubDesk


class StorageCurveDesk(StubDesk):
    name: str = "storage_curve"
    spec_path: str = "desks/storage_curve/spec.md"
    event_id: str = "cftc_cot"
    horizon_days: int = 7
