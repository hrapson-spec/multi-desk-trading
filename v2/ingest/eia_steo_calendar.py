"""EIA STEO release calendar ingester (calendar-only, v1.0).

Emits one PIT decision event per Short-Term Energy Outlook release.
EIA publishes STEO monthly on the second Tuesday at noon ET. A small
number of historical releases shifted by 1-2 days due to operational
or holiday reasons (e.g. April 2020 was pulled earlier during the
COVID disruption). v1.0 of this ingester encodes the deterministic
"2nd Tuesday at 12:00 ET" rule and marks the vintage_quality as
``release_lag_safe_revision_unknown`` to flag that the dates have not
been individually verified against the publisher's archive.

A future v1.1 will switch to live HTML scraping of
``https://www.eia.gov/outlooks/steo/archive.php`` to capture the
exact issue dates and (separately) the issue tables. v1.0 is
sufficient for harness counting because the harness only requires
``usable_after_ts`` accuracy within the embargo window (±5 days).
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
SCRAPER_VERSION = "v2.eia_steo_calendar.0"
LATENCY_GUARD_MINUTES = 5
RELEASE_TIME_ET = time(12, 0)  # noon ET; recent EIA STEO release time
SOURCE_URL = "https://www.eia.gov/outlooks/steo/archive.php"


# Historical exceptions to the 2nd-Tuesday rule, keyed by (year, month).
# Each value is the actual release date used. Format: ((year, month) -> date).
# v1.0 records only the well-known COVID-era April 2020 adjustment; a
# v1.1 audit pass should fill in any other shifts found in the archive.
RELEASE_DATE_OVERRIDES: dict[tuple[int, int], date] = {
    (2020, 4): date(2020, 4, 7),  # COVID disruption pulled April 2020 STEO earlier
}


@dataclass(frozen=True)
class STEOEvent:
    issue_year: int
    issue_month: int
    release_date: date
    release_ts_utc: datetime
    usable_after_ts_utc: datetime


def _second_tuesday(year: int, month: int) -> date:
    """2nd Tuesday of a calendar month."""
    first = date(year, month, 1)
    # Tuesday weekday() == 1
    offset = (1 - first.weekday()) % 7
    first_tuesday = date(year, month, 1 + offset)
    return first_tuesday + timedelta(days=7)


def _release_date_for(year: int, month: int) -> date:
    if (year, month) in RELEASE_DATE_OVERRIDES:
        return RELEASE_DATE_OVERRIDES[(year, month)]
    return _second_tuesday(year, month)


def _release_ts_utc(d: date) -> datetime:
    return datetime.combine(d, RELEASE_TIME_ET, tzinfo=NY).astimezone(UTC)


def all_events(
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[STEOEvent]:
    """Generate scheduled STEO events in [since, until]."""
    if since is None:
        since = date(2020, 1, 1)
    if until is None:
        until = date.today()
    if since > until:
        return []

    events: list[STEOEvent] = []
    y, m = since.year, since.month
    end_y, end_m = until.year, until.month
    while (y, m) <= (end_y, end_m):
        d = _release_date_for(y, m)
        if since <= d <= until:
            ts = _release_ts_utc(d)
            events.append(
                STEOEvent(
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


class EIASTEOCalendarIngester(BaseIngester):
    """Emit STEO release-calendar decision events to the PIT store.

    Data payload per event is a minimal one-row DataFrame containing the
    release metadata. Series content (price forecasts, balance tables) is
    OUT OF SCOPE for v1.0; this ingester only feeds the harness's
    decision-event counter.

    vintage_quality = release_lag_safe_revision_unknown because v1.0
    computes release dates from the 2nd-Tuesday rule rather than parsing
    the publisher's archive index. A future v1.1 will replace this with
    archive scraping and upgrade the quality to true_first_release.
    """

    name = "eia_steo_calendar"
    source = "eia_steo"

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
                    dataset="steo_calendar",
                    series="steo_release",
                    release_ts=ev.release_ts_utc,
                    usable_after_ts=ev.usable_after_ts_utc,
                    revision_ts=None,
                    data=data,
                    provenance={
                        "source": "eia_steo",
                        "method": "second_tuesday_rule_v1.0",
                        "scraper_version": SCRAPER_VERSION,
                        "publisher_url": SOURCE_URL,
                        "issue_label": issue_label,
                        "release_date": ev.release_date.isoformat(),
                        "had_override": (ev.issue_year, ev.issue_month)
                        in RELEASE_DATE_OVERRIDES,
                    },
                    vintage_quality=VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
                    observation_start=ev.release_date,
                    observation_end=ev.release_date,
                )
            )
        return results
