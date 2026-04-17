"""Release-calendar scheduler (spec §3.3).

Cron-style scheduler driven by two YAML configs:
  config/release_calendar.yaml — scheduled Print-producing events
  config/data_sources.yaml     — feed → desks mapping for ingestion-failure

For Week 0, scheduler is driven synthetically via advance_to(ts) — no daemon.
The live daemon variant is a Phase 1 step outside Week 0 scope.

advance_to semantics: fires all scheduled events with scheduled_ts_utc ≤ ts
that have not yet fired in this scheduler instance. Each firing emits a
scheduled trigger payload consumable by other scaffolding (e.g. the bus
for data_ingestion_failure).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from croniter import croniter

from bus import Bus
from contracts.v1 import ResearchLoopEvent

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CALENDAR = REPO_ROOT / "config" / "release_calendar.yaml"
DEFAULT_DATA_SOURCES = REPO_ROOT / "config" / "data_sources.yaml"


@dataclass(frozen=True)
class ScheduledEvent:
    event_id: str
    description: str
    cron: str
    tz: str
    target_variable: str


@dataclass(frozen=True)
class DataSource:
    feed_name: str
    description: str
    tolerance_minutes: int
    consumed_by: tuple[str, ...]


@dataclass
class Scheduler:
    events: list[ScheduledEvent]
    data_sources: dict[str, DataSource]
    bus: Bus | None = None
    last_ts_utc: datetime | None = None
    fired_event_keys: set[tuple[str, datetime]] = field(default_factory=set)

    @classmethod
    def from_config(
        cls,
        calendar_path: Path = DEFAULT_CALENDAR,
        data_sources_path: Path = DEFAULT_DATA_SOURCES,
        bus: Bus | None = None,
    ) -> Scheduler:
        with open(calendar_path) as fh:
            cal_raw = yaml.safe_load(fh) or {"events": []}
        with open(data_sources_path) as fh:
            ds_raw = yaml.safe_load(fh) or {"data_sources": []}
        events = [
            ScheduledEvent(
                event_id=e["event_id"],
                description=e["description"],
                cron=e["cron"],
                tz=e["tz"],
                target_variable=e["target_variable"],
            )
            for e in cal_raw.get("events", [])
        ]
        data_sources = {
            s["feed_name"]: DataSource(
                feed_name=s["feed_name"],
                description=s["description"],
                tolerance_minutes=int(s["tolerance_minutes"]),
                consumed_by=tuple(s.get("consumed_by", [])),
            )
            for s in ds_raw.get("data_sources", [])
        }
        return cls(events=events, data_sources=data_sources, bus=bus)

    # ----- firing -----------------------------------------------------

    def firings_between(
        self, start_utc: datetime, end_utc: datetime
    ) -> list[tuple[ScheduledEvent, datetime]]:
        """All (event, scheduled_ts_utc) within (start, end] in cron order."""
        results: list[tuple[ScheduledEvent, datetime]] = []
        for ev in self.events:
            tz = ZoneInfo(ev.tz)
            start_local = start_utc.astimezone(tz)
            it = croniter(ev.cron, start_time=start_local)
            while True:
                ts_local: datetime = it.get_next(datetime)
                ts_utc = ts_local.astimezone(UTC)
                if ts_utc > end_utc:
                    break
                if ts_utc <= start_utc:
                    continue
                results.append((ev, ts_utc))
        results.sort(key=lambda x: x[1])
        return results

    def advance_to(self, ts_utc: datetime) -> list[tuple[ScheduledEvent, datetime]]:
        """Move the clock forward to ts_utc; return firings since last advance.

        Idempotent on re-call with the same ts_utc: a given (event_id,
        scheduled_ts_utc) pair fires at most once per Scheduler instance.
        """
        start = self.last_ts_utc if self.last_ts_utc is not None else ts_utc - timedelta(days=365)
        if ts_utc <= start:
            return []
        firings = self.firings_between(start, ts_utc)
        fresh: list[tuple[ScheduledEvent, datetime]] = []
        for ev, ts in firings:
            key = (ev.event_id, ts)
            if key in self.fired_event_keys:
                continue
            self.fired_event_keys.add(key)
            fresh.append((ev, ts))
        self.last_ts_utc = ts_utc
        return fresh

    # ----- ingestion-failure emission --------------------------------

    def emit_ingestion_failure(
        self,
        feed_name: str,
        scheduled_release_ts: datetime,
        actual_wall_clock_ts: datetime,
    ) -> ResearchLoopEvent:
        """Build (and, if a bus is attached, publish) a data_ingestion_failure event.

        Payload key alignment (v1.7): outbound key is `affected_desks`,
        matching the handler contract. The underlying config key in
        data_sources.yaml remains `consumed_by` — renaming in the
        outbound payload keeps the wire contract stable under config
        evolution.
        """
        ds = self.data_sources.get(feed_name)
        payload: dict[str, object] = {
            "feed_name": feed_name,
            "scheduled_release_ts_utc": scheduled_release_ts.isoformat(),
            "actual_wall_clock_ts_utc": actual_wall_clock_ts.isoformat(),
            "affected_desks": list(ds.consumed_by) if ds is not None else [],
        }
        event = ResearchLoopEvent(
            event_id=str(uuid.uuid4()),
            event_type="data_ingestion_failure",
            triggered_at_utc=actual_wall_clock_ts,
            priority=1,
            payload=payload,
        )
        if self.bus is not None:
            self.bus.publish_research_event(event)
        return event

    def check_ingestion_misses(
        self,
        now_utc: datetime,
        actual_prints_per_feed: dict[str, list[datetime]],
    ) -> list[ResearchLoopEvent]:
        """For each scheduled release ≤ now, if no matching Print lies within
        tolerance, emit a data_ingestion_failure."""
        emitted: list[ResearchLoopEvent] = []
        firings = self.firings_between(now_utc - timedelta(days=14), now_utc)
        for ev, scheduled_ts in firings:
            ds = self.data_sources.get(ev.event_id)
            tolerance = timedelta(minutes=ds.tolerance_minutes if ds is not None else 120)
            deadline = scheduled_ts + tolerance
            if now_utc < deadline:
                continue
            prints_for_feed = actual_prints_per_feed.get(ev.event_id, [])
            if any(
                abs((p - scheduled_ts).total_seconds()) <= tolerance.total_seconds()
                for p in prints_for_feed
            ):
                continue
            emitted.append(self.emit_ingestion_failure(ev.event_id, scheduled_ts, now_utc))
        return emitted


__all__: Iterable[str] = [
    "Scheduler",
    "ScheduledEvent",
    "DataSource",
    "DEFAULT_CALENDAR",
    "DEFAULT_DATA_SOURCES",
]
