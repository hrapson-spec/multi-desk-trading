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
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import yaml
from croniter import croniter

from bus import Bus
from contracts.v1 import ResearchLoopEvent

if TYPE_CHECKING:
    import duckdb

    from research_loop.dispatcher import Dispatcher

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

    def check_latency_drift(
        self,
        conn: duckdb.DuckDBPyConnection,
        now_utc: datetime,
        actual_prints_per_feed: dict[str, list[datetime]],
    ) -> list[ResearchLoopEvent]:
        """Page-Hinkley early-warning path (spec §14.5 v1.7, Layer 3).

        For every scheduled firing in the lookback, compute observed
        latency (Print-arrival − scheduled_ts if matched within tolerance,
        else `now − scheduled_ts` — still pending). Feeds the stream
        through a per-feed Page-Hinkley detector; when the detector
        newly trips AND no feed_incidents row is currently open for
        that feed, emits a preemptive `data_ingestion_failure` with
        `detected_by='page_hinkley'`.

        Complementary to `check_ingestion_misses` (tolerance-window path):
          - scheduler: detects step-change misses (deadline passed, no
            Print).
          - page_hinkley: detects slow drift before the deadline.
          - Both paths are belt-and-braces; handler idempotency ensures
            at most one open feed_incident per feed at any time.

        Accepts `conn` as an explicit parameter (not on Scheduler state)
        so existing scheduler callers are unaffected.
        """
        from persistence import get_open_feed_incidents
        from research_loop.feed_latency_monitor import observe_latency

        emitted: list[ResearchLoopEvent] = []
        firings = self.firings_between(now_utc - timedelta(days=14), now_utc)
        for ev, scheduled_ts in firings:
            feed = ev.event_id
            ds = self.data_sources.get(feed)
            tolerance = timedelta(minutes=ds.tolerance_minutes if ds is not None else 120)
            prints_for_feed = actual_prints_per_feed.get(feed, [])
            # Choose an arrival time to compare against scheduled_ts. If
            # any Print landed within the tolerance window, use the
            # nearest; otherwise treat the feed as still pending and
            # use `now_utc` (clipped to non-negative).
            matched = [
                p
                for p in prints_for_feed
                if abs((p - scheduled_ts).total_seconds()) <= tolerance.total_seconds()
            ]
            if matched:
                arrival = min(matched, key=lambda p: abs((p - scheduled_ts).total_seconds()))
            else:
                arrival = now_utc
            latency_seconds = max(0.0, (arrival - scheduled_ts).total_seconds())
            _, newly_tripped = observe_latency(
                conn,
                feed_name=feed,
                latency_seconds=latency_seconds,
                now_utc=now_utc,
            )
            if not newly_tripped:
                continue
            if get_open_feed_incidents(conn, feed_name=feed):
                # An incident is already open — scheduler path beat us
                # to it. Don't duplicate-emit; the PH trip is recorded
                # in feed_latency_state for diagnostic purposes.
                continue
            # Emit a preemptive failure event tagged page_hinkley.
            event = self.emit_ingestion_failure(feed, scheduled_ts, now_utc)
            # Copy-override the detected_by key so the handler records
            # the source correctly.
            new_payload = dict(event.payload)
            new_payload["detected_by"] = "page_hinkley"
            emitted.append(
                ResearchLoopEvent(
                    event_id=event.event_id,
                    event_type=event.event_type,
                    triggered_at_utc=event.triggered_at_utc,
                    priority=event.priority,
                    payload=new_payload,
                )
            )
        return emitted

    def check_incident_recoveries(
        self,
        conn: duckdb.DuckDBPyConnection,
        now_utc: datetime,
        actual_prints_per_feed: dict[str, list[datetime]],
    ) -> list[str]:
        """Close feed_incidents when Prints resume (§14.5 v1.7 recovery).

        For each currently-open feed_incidents row: find the next
        scheduled firing AFTER the incident's opened_ts_utc; if a Print
        for that feed landed within tolerance of that firing, close the
        incident AND reset the Page-Hinkley detector via
        `feed_latency_monitor.reset_for_feed` (so the next drift episode
        is detected against a clean baseline).

        Returns the list of feed_names whose incidents were closed.

        Semantics:
          - Healthy-resume signal = one scheduled firing post-open whose
            release landed on time. A single on-time Print is enough to
            declare the feed healthy; more would be conservative but
            also delays reinstatement for no load-bearing reason.
          - Closure is NOT idempotent on the first call (writes
            closed_ts_utc), but IS a no-op on subsequent calls because
            the handler only returns feeds whose incidents are
            currently open.
        """
        from persistence import (
            close_feed_incident,
            get_open_feed_incidents,
        )
        from research_loop.feed_latency_monitor import reset_for_feed

        closed: list[str] = []
        for incident in get_open_feed_incidents(conn):
            feed = str(incident["feed_name"])
            opened_ts = incident["opened_ts_utc"]
            assert isinstance(opened_ts, datetime)
            ds = self.data_sources.get(feed)
            tolerance = timedelta(minutes=ds.tolerance_minutes if ds is not None else 120)
            # Only firings AFTER opened_ts count as recovery signals —
            # a Print that arrived BEFORE the incident was opened has
            # already been classified as late by the opening path.
            firings = [
                (ev, ts)
                for ev, ts in self.firings_between(opened_ts, now_utc)
                if ev.event_id == feed
            ]
            prints_for_feed = actual_prints_per_feed.get(feed, [])
            recovered = False
            for _ev, scheduled_ts in firings:
                if any(
                    abs((p - scheduled_ts).total_seconds()) <= tolerance.total_seconds()
                    for p in prints_for_feed
                ):
                    recovered = True
                    break
            if not recovered:
                continue
            close_feed_incident(
                conn,
                feed_incident_id=str(incident["feed_incident_id"]),
                closed_ts_utc=now_utc,
                resolution_artefact=f"auto:scheduler_recovery:{feed}",
            )
            reset_for_feed(conn, feed)
            closed.append(feed)
        return closed

    def submit_feed_reliability_review(
        self,
        dispatcher: Dispatcher,
        *,
        now_utc: datetime,
        feed_names: list[str] | None = None,
        **payload_overrides: object,
    ) -> ResearchLoopEvent:
        """Submit a feed_reliability_review event to the dispatcher
        (spec §6.2, §14.5 v1.7 Layer 2 periodic review).

        If `feed_names` is None, defaults to every feed in the
        scheduler's data_sources config — i.e. review all known feeds.
        Extra payload kwargs override defaults (lookback_days,
        retirement_threshold, recovery_days,
        max_retirements_per_7_days, reinstate_weight).

        Returns the ResearchLoopEvent that was submitted (already
        persisted by dispatcher.submit).

        This helper is intended to be called on a periodic cadence —
        weekly by default per §6.3 — by the long-running process
        (soak runner, production daemon, or manual operator script).
        The helper itself does NOT schedule the cadence; that's the
        caller's responsibility.
        """
        if feed_names is None:
            feed_names = sorted(self.data_sources.keys())
        payload: dict[str, object] = {"feed_names": feed_names}
        payload.update(payload_overrides)
        event = ResearchLoopEvent(
            event_id=str(uuid.uuid4()),
            event_type="feed_reliability_review",
            triggered_at_utc=now_utc,
            priority=2,
            payload=payload,
        )
        dispatcher.submit(event)
        return event


__all__: Iterable[str] = [
    "Scheduler",
    "ScheduledEvent",
    "DataSource",
    "DEFAULT_CALENDAR",
    "DEFAULT_DATA_SOURCES",
]
