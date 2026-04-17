"""Resource telemetry for the Reliability-gate runner (plan fix 4).

Samples process RSS, open file descriptors, DuckDB file size, elapsed
wall-time, and the running decision count. Each sample is persisted to
the `soak_resource_samples` table so operators can inspect a run
post-hoc without re-running it.

Cadence defaults to 60 s. Uses `psutil.Process()` for cross-platform
RSS + FD counts (the stdlib `resource` module is POSIX-only and
doesn't expose open-FD count cleanly).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import psutil

from contracts.v1 import SoakResourceSample
from persistence import insert_soak_resource_sample


@dataclass
class ResourceMonitor:
    """Samples resource usage and persists each sample.

    Stateless-ish: holds a process handle + start timestamp + a
    decision-count delegate (callable that returns current count).
    The caller drives `.sample()` at whatever cadence they prefer;
    the monitor itself doesn't sleep.
    """

    conn: duckdb.DuckDBPyConnection
    db_path: Path
    decision_count_fn: object  # Callable[[], int]; avoid typing.Callable import
    start_ts_utc: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    _process: psutil.Process = field(init=False)

    def __post_init__(self) -> None:
        self._process = psutil.Process(os.getpid())

    def sample(self, *, now_utc: datetime | None = None) -> SoakResourceSample:
        """Take one resource sample and persist it. Returns the record."""
        ts = now_utc if now_utc is not None else datetime.now(tz=UTC)
        elapsed = (ts - self.start_ts_utc).total_seconds()
        # psutil returns RSS in bytes on all platforms.
        rss = int(self._process.memory_info().rss)
        # num_fds is POSIX; on Windows psutil has num_handles. Fall back to
        # handles on Windows so the monitor still works cross-platform.
        try:
            fd_count = int(self._process.num_fds())
        except AttributeError:  # pragma: no cover — Windows path
            fd_count = int(self._process.num_handles())
        db_size = int(self.db_path.stat().st_size) if self.db_path.exists() else 0
        n_decisions = int(self.decision_count_fn())  # type: ignore[operator]

        sample = SoakResourceSample(
            sample_id=str(uuid.uuid4()),
            ts_utc=ts,
            elapsed_seconds=float(elapsed),
            rss_bytes=rss,
            open_fds=fd_count,
            db_size_bytes=db_size,
            n_decisions=n_decisions,
        )
        insert_soak_resource_sample(self.conn, sample)
        return sample
