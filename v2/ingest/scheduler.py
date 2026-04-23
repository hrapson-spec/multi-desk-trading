"""Ingestion scheduler.

v2.0 scope: run each registered ingester once per daily EOD tick after
16:30 ET. Failures in one ingester must not abort the others.

This is deliberately minimal at v2.0. A full cron-driven implementation
(per-source cadence, retries, alerting) lands alongside the live-feed
wiring in the same cycle as the first real ingester implementation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from v2.ingest.base import Ingester
from v2.pit_store.writer import WriteResult

logger = logging.getLogger(__name__)


@dataclass
class ScheduledIngester:
    ingester: Ingester
    enabled: bool = True


@dataclass
class IngestReport:
    started_at: datetime
    finished_at: datetime
    as_of_ts: datetime
    per_source_success: dict[str, list[WriteResult]] = field(default_factory=dict)
    per_source_error: dict[str, str] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return len(self.per_source_error)

    @property
    def success_count(self) -> int:
        return sum(len(v) for v in self.per_source_success.values())


class IngestScheduler:
    def __init__(self) -> None:
        self._registered: list[ScheduledIngester] = []

    def register(self, ingester: Ingester, *, enabled: bool = True) -> None:
        self._registered.append(ScheduledIngester(ingester=ingester, enabled=enabled))

    @property
    def registered(self) -> list[ScheduledIngester]:
        return list(self._registered)

    def run(self, as_of_ts: datetime) -> IngestReport:
        started = _utcnow()
        report = IngestReport(started_at=started, finished_at=started, as_of_ts=as_of_ts)
        for entry in self._registered:
            if not entry.enabled:
                continue
            name = entry.ingester.name
            try:
                results = entry.ingester.ingest(as_of_ts)
                report.per_source_success[name] = list(results)
            except Exception as exc:  # noqa: BLE001 — intentionally catch-all for scheduler isolation
                logger.exception("ingester %s failed", name)
                report.per_source_error[name] = f"{type(exc).__name__}: {exc}"
        report.finished_at = _utcnow()
        return report


def _utcnow() -> datetime:
    from datetime import UTC  # keep import-local to avoid module-level warnings

    return datetime.now(UTC)
