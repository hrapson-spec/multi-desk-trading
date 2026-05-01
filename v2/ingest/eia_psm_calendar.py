"""EIA Petroleum Supply Monthly (EIA-914) release calendar ingester (v1.0).

Emits one PIT decision event per Petroleum Supply Monthly (preliminary)
release. EIA publishes PSM around the last Friday of each month at
10:00 ET (with the data covering production from ~2 months prior). The
"final" issue follows ~1 month after the preliminary; per spec §3,
only the first release counts as a decision event. v1.0 of this
ingester encodes the deterministic "last Friday of the month at 10:00
ET" rule and marks vintage_quality as `release_lag_safe_revision_unknown`.

A future v1.1 will switch to live HTML scraping of
``https://www.eia.gov/petroleum/supply/monthly/archive/`` to capture
the exact issue dates. v1.0 is sufficient for harness counting.
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
SCRAPER_VERSION = "v2.eia_psm_calendar.0"
LATENCY_GUARD_MINUTES = 5
RELEASE_TIME_ET = time(10, 0)
SOURCE_URL = "https://www.eia.gov/petroleum/supply/monthly/archive/"


@dataclass(frozen=True)
class PSMEvent:
    issue_year: int
    issue_month: int
    release_date: date
    release_ts_utc: datetime
    usable_after_ts_utc: datetime


def _last_friday(year: int, month: int) -> date:
    """Last Friday of a calendar month."""
    # First day of next month, then walk back to Friday
    first_of_next = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last_day = first_of_next - timedelta(days=1)
    # Friday weekday() == 4
    offset = (last_day.weekday() - 4) % 7
    return last_day - timedelta(days=offset)


def _release_ts_utc(d: date) -> datetime:
    return datetime.combine(d, RELEASE_TIME_ET, tzinfo=NY).astimezone(UTC)


def all_events(
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[PSMEvent]:
    if since is None:
        since = date(2020, 1, 1)
    if until is None:
        until = date.today()
    if since > until:
        return []

    events: list[PSMEvent] = []
    y, m = since.year, since.month
    end_y, end_m = until.year, until.month
    while (y, m) <= (end_y, end_m):
        d = _last_friday(y, m)
        if since <= d <= until:
            ts = _release_ts_utc(d)
            events.append(
                PSMEvent(
                    issue_year=y,
                    issue_month=m,
                    release_date=d,
                    release_ts_utc=ts,
                    usable_after_ts_utc=ts + timedelta(minutes=LATENCY_GUARD_MINUTES),
                )
            )
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return events


class EIAPSMCalendarIngester(BaseIngester):
    """Emit PSM (EIA-914 preliminary) release-calendar decision events.

    Data payload per event is a minimal one-row DataFrame containing the
    release metadata. Series content (production tables) is OUT OF SCOPE
    for v1.0; v1.1 will add the parsed table values.
    """

    name = "eia_psm_calendar"
    source = "eia_psm"

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
            issue_label = f"{ev.issue_year}-{ev.issue_month:02d}"
            data = pd.DataFrame(
                {
                    "issue_label": [issue_label],
                    "release_date": [ev.release_date.isoformat()],
                    "release_ts_utc": [ev.release_ts_utc.isoformat()],
                    "usable_after_ts_utc": [ev.usable_after_ts_utc.isoformat()],
                    "frequency": ["monthly"],
                }
            )
            results.append(
                FetchResult(
                    source=self.source,
                    dataset="psm_calendar",
                    series="psm_release",
                    release_ts=ev.release_ts_utc,
                    usable_after_ts=ev.usable_after_ts_utc,
                    revision_ts=None,
                    data=data,
                    provenance={
                        "source": "eia_psm",
                        "method": "last_friday_rule_v1.0",
                        "scraper_version": SCRAPER_VERSION,
                        "publisher_url": SOURCE_URL,
                        "issue_label": issue_label,
                        "release_date": ev.release_date.isoformat(),
                    },
                    vintage_quality=VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
                    observation_start=ev.release_date,
                    observation_end=ev.release_date,
                )
            )
        return results
