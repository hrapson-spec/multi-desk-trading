"""Caldara-Iacoviello Geopolitical Risk Index calendar ingester (v1.0).

Caldara-Iacoviello publish weekly GPR series via
https://www.matteoiacoviello.com/gpr.htm. Updates land Friday morning
ET. v1.0 emits one decision event per Friday of the post-2020 window
with vintage_quality `release_lag_safe_revision_unknown` (calendar
inferred from the publishing pattern; not scraped per-issue).

The data payload carried by each event is minimal — the harness only
needs the timestamp. v1.1 will add the actual GPR series values
parsed from the published CSV.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.quality import VintageQuality
from v2.pit_store.writer import PITWriter

NY = ZoneInfo("America/New_York")
SCRAPER_VERSION = "v2.gpr_calendar.0"
LATENCY_GUARD_MINUTES = 5
RELEASE_TIME_ET = time(9, 0)  # Friday morning publication
SOURCE_URL = "https://www.matteoiacoviello.com/gpr.htm"


@dataclass(frozen=True)
class GPREvent:
    week_friday: date
    release_ts_utc: datetime
    usable_after_ts_utc: datetime


def _release_ts_utc(d: date) -> datetime:
    return datetime.combine(d, RELEASE_TIME_ET, tzinfo=NY).astimezone(UTC)


def all_events(
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[GPREvent]:
    if since is None:
        since = date(2020, 1, 1)
    if until is None:
        until = date.today()
    if since > until:
        return []
    # Walk Fridays (weekday == 4)
    cur = since + timedelta(days=(4 - since.weekday()) % 7)
    events: list[GPREvent] = []
    while cur <= until:
        ts = _release_ts_utc(cur)
        events.append(
            GPREvent(
                week_friday=cur,
                release_ts_utc=ts,
                usable_after_ts_utc=ts + timedelta(minutes=LATENCY_GUARD_MINUTES),
            )
        )
        cur += timedelta(days=7)
    return events


class GPRCalendarIngester(BaseIngester):
    """Emit GPR weekly Friday decision events to the PIT store."""

    name = "gpr_calendar"
    source = "caldara_iacoviello"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        since: date | None = None,
        until: date | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        self._since = since
        self._until = until

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        del as_of_ts
        events = all_events(since=self._since, until=self._until)
        results: list[FetchResult] = []
        for ev in events:
            data = pd.DataFrame(
                {
                    "week_friday": [ev.week_friday.isoformat()],
                    "release_ts_utc": [ev.release_ts_utc.isoformat()],
                    "usable_after_ts_utc": [ev.usable_after_ts_utc.isoformat()],
                    "frequency": ["weekly_friday"],
                }
            )
            results.append(
                FetchResult(
                    source=self.source,
                    dataset="gpr_weekly",
                    series="gpr_weekly_release",
                    release_ts=ev.release_ts_utc,
                    usable_after_ts=ev.usable_after_ts_utc,
                    revision_ts=None,
                    data=data,
                    provenance={
                        "source": "caldara_iacoviello",
                        "method": "weekly_friday_rule_v1.0",
                        "scraper_version": SCRAPER_VERSION,
                        "publisher_url": SOURCE_URL,
                        "week_friday": ev.week_friday.isoformat(),
                    },
                    vintage_quality=VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
                    observation_start=ev.week_friday,
                    observation_end=ev.week_friday,
                )
            )
        return results
