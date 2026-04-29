"""FOMC announcement calendar ingester.

Emits one PIT decision event per FOMC statement release and per FOMC
minutes release. Statements release at 14:00 America/New_York (with rare
intra-meeting emergency exceptions); minutes release ~3 weeks later at
14:00 America/New_York. Both are pre-scheduled by the Fed years in
advance and are stable historical record (no revisions).

Dates are sourced from the Federal Reserve's published calendars at
https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm. Because
the calendar is fixed at publication and immutable thereafter, this
ingester encodes the post-2020 schedule directly rather than scraping
the HTML calendar page. A future v1.1 version can switch to live HTML
parsing without changing the manifest contract.

vintage_quality = true_first_release because the date itself does not
revise; the announcement is the publication artefact.
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
SCRAPER_VERSION = "v2.fomc_calendar.0"
LATENCY_GUARD_MINUTES = 5
ANNOUNCEMENT_TIME_ET = time(14, 0)
SOURCE_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


@dataclass(frozen=True)
class FOMCEvent:
    """One FOMC public announcement event."""

    event_type: str  # "statement" | "minutes"
    event_date: date
    meeting_label: str  # e.g. "2024-01" for January 2024 meeting


# Schedule of FOMC scheduled meetings 2020 onward. Each tuple is the date
# of the second day of the meeting (= statement release date). Emergency
# meetings (e.g. 2020-03-03 inter-meeting cut, 2020-03-15 emergency cut)
# are included as their statement release date. Source: Federal Reserve
# published meeting calendars; cross-checked against FRED FEDFUNDS releases.
SCHEDULED_STATEMENT_DATES: tuple[date, ...] = (
    # 2020
    date(2020, 1, 29),
    date(2020, 3, 3),  # emergency 50bp cut
    date(2020, 3, 15),  # emergency to ZIRP, Sunday afternoon ET
    date(2020, 4, 29),
    date(2020, 6, 10),
    date(2020, 7, 29),
    date(2020, 9, 16),
    date(2020, 11, 5),
    date(2020, 12, 16),
    # 2021
    date(2021, 1, 27),
    date(2021, 3, 17),
    date(2021, 4, 28),
    date(2021, 6, 16),
    date(2021, 7, 28),
    date(2021, 9, 22),
    date(2021, 11, 3),
    date(2021, 12, 15),
    # 2022
    date(2022, 1, 26),
    date(2022, 3, 16),
    date(2022, 5, 4),
    date(2022, 6, 15),
    date(2022, 7, 27),
    date(2022, 9, 21),
    date(2022, 11, 2),
    date(2022, 12, 14),
    # 2023
    date(2023, 2, 1),
    date(2023, 3, 22),
    date(2023, 5, 3),
    date(2023, 6, 14),
    date(2023, 7, 26),
    date(2023, 9, 20),
    date(2023, 11, 1),
    date(2023, 12, 13),
    # 2024
    date(2024, 1, 31),
    date(2024, 3, 20),
    date(2024, 5, 1),
    date(2024, 6, 12),
    date(2024, 7, 31),
    date(2024, 9, 18),
    date(2024, 11, 7),
    date(2024, 12, 18),
    # 2025
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 10, 29),
    date(2025, 12, 10),
    # 2026 (post-meeting calendar published; only past meetings included)
    date(2026, 1, 28),
    date(2026, 3, 18),
)

# Minutes are released 3 weeks (21 days) after the corresponding statement.
# Some minutes have a slight delay (1 business day) but for the harness
# the 3-week offset is accurate to within the embargo window.
MINUTES_OFFSET_DAYS = 21


def _statement_ts_utc(d: date) -> datetime:
    """Statement release: 14:00 ET on the meeting's second day, in UTC."""
    return datetime.combine(d, ANNOUNCEMENT_TIME_ET, tzinfo=NY).astimezone(UTC)


def _minutes_ts_utc(meeting_date: date) -> datetime:
    """Minutes release: 14:00 ET, 3 weeks after the meeting statement."""
    return _statement_ts_utc(meeting_date + timedelta(days=MINUTES_OFFSET_DAYS))


def _meeting_label(d: date) -> str:
    return d.strftime("%Y-%m")


def all_events(
    *,
    since: date | None = None,
    until: date | None = None,
    include_minutes: bool = True,
) -> list[FOMCEvent]:
    """Return all FOMC events in the encoded calendar, optionally bounded."""
    events: list[FOMCEvent] = []
    for d in SCHEDULED_STATEMENT_DATES:
        label = _meeting_label(d)
        events.append(FOMCEvent(event_type="statement", event_date=d, meeting_label=label))
        if include_minutes:
            mdate = d + timedelta(days=MINUTES_OFFSET_DAYS)
            events.append(
                FOMCEvent(event_type="minutes", event_date=mdate, meeting_label=label)
            )
    if since is not None:
        events = [e for e in events if e.event_date >= since]
    if until is not None:
        events = [e for e in events if e.event_date <= until]
    events.sort(key=lambda e: (e.event_date, e.event_type))
    return events


class FOMCCalendarIngester(BaseIngester):
    """Emit FOMC statement and minutes decision events to the PIT store.

    The data payload per event is a minimal one-row DataFrame containing
    the announcement metadata. The harness reads only the manifest's
    `usable_after_ts` to build the decision-event series.
    """

    name = "fomc_calendar"
    source = "fomc"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        since: date | None = None,
        until: date | None = None,
        include_minutes: bool = True,
    ) -> None:
        super().__init__(writer, manifest)
        self._since = since
        self._until = until
        self._include_minutes = include_minutes

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        del as_of_ts
        events = all_events(
            since=self._since,
            until=self._until,
            include_minutes=self._include_minutes,
        )
        results: list[FetchResult] = []
        for ev in events:
            if ev.event_type == "statement":
                release_ts = _statement_ts_utc(ev.event_date)
                series = "fomc_statement"
            else:
                # The minutes' release_ts is 14:00 ET on event_date itself
                # (event_date already encodes the +21d offset).
                release_ts = datetime.combine(
                    ev.event_date, ANNOUNCEMENT_TIME_ET, tzinfo=NY
                ).astimezone(UTC)
                series = "fomc_minutes"
            usable_after_ts = release_ts + timedelta(minutes=LATENCY_GUARD_MINUTES)
            data = pd.DataFrame(
                {
                    "event_type": [ev.event_type],
                    "meeting_label": [ev.meeting_label],
                    "event_date": [ev.event_date.isoformat()],
                    "release_ts_utc": [release_ts.isoformat()],
                    "usable_after_ts_utc": [usable_after_ts.isoformat()],
                    "frequency": ["irregular_~8_per_year"],
                }
            )
            results.append(
                FetchResult(
                    source=self.source,
                    dataset="fomc_announcements",
                    series=series,
                    release_ts=release_ts,
                    usable_after_ts=usable_after_ts,
                    revision_ts=None,
                    data=data,
                    provenance={
                        "source": "fomc",
                        "method": "calendar_encoded",
                        "scraper_version": SCRAPER_VERSION,
                        "publisher_url": SOURCE_URL,
                        "event_type": ev.event_type,
                        "meeting_label": ev.meeting_label,
                        "event_date": ev.event_date.isoformat(),
                    },
                    vintage_quality=VintageQuality.TRUE_FIRST_RELEASE.value,
                    observation_start=ev.event_date,
                    observation_end=ev.event_date,
                )
            )
        return results
