"""Numerically-thresholded incident detection (plan fix 5).

Replaces the v1.5 spec's hand-wavy "zero infrastructure incidents"
with concrete pass/fail rules. Thresholds are pre-registered:

  - memory_leak: RSS growth > `rss_growth_threshold` (default 20 % over
    a rolling 24 h window, or > 500 MB absolute growth over the run).
  - fd_leak: open-FD count > `fd_multiplier` × initial FD count
    (default 5 ×).
  - disk_growth: DuckDB file growth > `db_growth_bytes` (default 5 GB).

Exception-derived incidents (scheduler_crash, db_corruption,
bus_validation_inconsistency) are raised by the dispatching code;
`record_exception()` classifies + persists them.

Gate failures (desk Gate 1/2/3 misses during the soak run) are NOT
incidents per §12.2 — the caller simply doesn't route them through
this module.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import duckdb

from contracts.v1 import SoakIncident, SoakResourceSample
from persistence import insert_soak_incident

IncidentClass = Literal[
    "memory_leak",
    "fd_leak",
    "disk_growth",
    "scheduler_crash",
    "db_corruption",
    "bus_validation_inconsistency",
]


@dataclass
class IncidentThresholds:
    """Pre-registered numeric thresholds — changing these is a v1.x spec
    revision, not a silent tuning parameter."""

    rss_growth_ratio: float = 1.20  # 20 % growth over baseline
    rss_growth_abs_bytes: int = 500 * 1024 * 1024  # 500 MB
    fd_multiplier: float = 5.0
    db_growth_bytes: int = 5 * 1024 * 1024 * 1024  # 5 GB


@dataclass
class IncidentDetector:
    """Monitors resource samples + records exception-based incidents.

    Usage:
        det = IncidentDetector(conn)
        det.set_baseline(sample)   # first sample becomes the reference
        ...
        incident = det.check(sample)   # None if healthy
        ...
        det.record_exception(cls, detail)   # scheduler/db/bus failures
    """

    conn: duckdb.DuckDBPyConnection
    thresholds: IncidentThresholds = None  # type: ignore[assignment]
    _baseline: SoakResourceSample | None = None

    def __post_init__(self) -> None:
        if self.thresholds is None:
            self.thresholds = IncidentThresholds()

    def set_baseline(self, sample: SoakResourceSample) -> None:
        """Record the initial resource state — subsequent `.check()` calls
        compare against this."""
        self._baseline = sample

    def check(self, sample: SoakResourceSample) -> SoakIncident | None:
        """Evaluate a sample against thresholds. Returns the first detected
        incident (if any) and persists it; returns None if healthy."""
        if self._baseline is None:
            return None

        t = self.thresholds
        b = self._baseline

        # 1. Memory leak: either ratio or absolute growth
        rss_ratio = sample.rss_bytes / max(b.rss_bytes, 1)
        rss_abs_growth = sample.rss_bytes - b.rss_bytes
        if rss_ratio >= t.rss_growth_ratio and rss_abs_growth >= t.rss_growth_abs_bytes:
            return self._record(
                "memory_leak",
                {
                    "baseline_rss_bytes": b.rss_bytes,
                    "current_rss_bytes": sample.rss_bytes,
                    "ratio": rss_ratio,
                    "abs_growth_bytes": rss_abs_growth,
                    "threshold_ratio": t.rss_growth_ratio,
                    "threshold_abs_bytes": t.rss_growth_abs_bytes,
                },
            )

        # 2. FD leak
        if sample.open_fds >= b.open_fds * t.fd_multiplier and sample.open_fds > 0:
            return self._record(
                "fd_leak",
                {
                    "baseline_open_fds": b.open_fds,
                    "current_open_fds": sample.open_fds,
                    "multiplier": t.fd_multiplier,
                },
            )

        # 3. Disk growth
        if sample.db_size_bytes - b.db_size_bytes >= t.db_growth_bytes:
            return self._record(
                "disk_growth",
                {
                    "baseline_db_bytes": b.db_size_bytes,
                    "current_db_bytes": sample.db_size_bytes,
                    "threshold_bytes": t.db_growth_bytes,
                },
            )

        return None

    def record_exception(
        self,
        incident_class: IncidentClass,
        detail: dict[str, object],
    ) -> SoakIncident:
        """Persist an exception-derived incident (scheduler_crash,
        db_corruption, bus_validation_inconsistency)."""
        if incident_class not in {
            "scheduler_crash",
            "db_corruption",
            "bus_validation_inconsistency",
        }:
            raise ValueError(
                f"record_exception only handles runtime-failure classes; got {incident_class!r}"
            )
        return self._record(incident_class, detail)

    def _record(self, cls: IncidentClass, detail: dict[str, object]) -> SoakIncident:
        incident = SoakIncident(
            incident_id=str(uuid.uuid4()),
            detected_ts_utc=datetime.now(tz=UTC),
            incident_class=cls,
            detail=detail,
        )
        insert_soak_incident(self.conn, incident)
        return incident
