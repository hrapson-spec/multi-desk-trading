"""OPEC ministerial / JMMC announcement calendar ingester (v1.0).

Emits one PIT decision event per OPEC+ Ministerial Meeting and per major
Joint Ministerial Monitoring Committee announcement post-2020. v1.0
encodes a curated list of well-documented headline events (OPEC+
Ministerial Meetings, Ordinary OPEC Conferences, and the
production-changing emergency JMMC announcements during 2020-2025).
Routine technical JMMCs that produced no production-changing
announcement are out of scope.

Release time is approximated as 14:00 Vienna (CET/CEST) which is the
typical communique time on meeting days. Many OPEC announcements come
late in the day or via press release several hours after the call;
v1.0 pins 14:00 CET as a conservative "earliest usable" timestamp.
The 30-minute latency guard (vs. 5min for WPSR/FOMC) reflects OPEC's
historical pattern of communique re-release within ~30min of the
initial wire.

vintage_quality = release_lag_safe_revision_unknown — v1.0 dates and
times are best-effort; v1.1 will replace with live scraping of
``https://www.opec.org/opec_web/en/press_room/`` for exact issue
timestamps.
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

VIENNA = ZoneInfo("Europe/Vienna")
SCRAPER_VERSION = "v2.opec_ministerial_calendar.0"
LATENCY_GUARD_MINUTES = 30
RELEASE_TIME_CET = time(14, 0)
SOURCE_URL = "https://www.opec.org/opec_web/en/press_room/"


@dataclass(frozen=True)
class OPECEvent:
    event_date: date
    event_label: str  # e.g. "OPEC+_11th_Ministerial"
    event_type: str  # "ministerial" | "jmmc_with_announcement" | "ordinary_conference"


# Curated post-2020 OPEC+ ministerial / JMMC events. Source basis:
# OPEC press releases archive cross-referenced with major news wire
# coverage. v1.0 covers events that produced production-quota,
# voluntary-cut, or production-hike announcements. Routine technical
# JMMCs that issued only "monitoring" communiques are excluded.
OPEC_EVENTS: tuple[OPECEvent, ...] = (
    # 2020 — COVID disruption + OPEC+ deadlock + emergency cuts
    OPECEvent(date(2020, 3, 6), "OPEC+_8th_Ministerial_failed", "ministerial"),
    OPECEvent(date(2020, 4, 9), "OPEC+_extraordinary_10mb_cut", "ministerial"),
    OPECEvent(date(2020, 4, 12), "G20_energy_ministers_OPEC+", "ministerial"),
    OPECEvent(date(2020, 6, 6), "OPEC+_11th_Ministerial", "ministerial"),
    OPECEvent(date(2020, 7, 15), "JMMC_20th", "jmmc_with_announcement"),
    OPECEvent(date(2020, 9, 17), "JMMC_22nd", "jmmc_with_announcement"),
    OPECEvent(date(2020, 10, 19), "JMMC_23rd", "jmmc_with_announcement"),
    OPECEvent(date(2020, 12, 1), "OPEC_180th_Conference_OPEC+_12th_Ministerial", "ministerial"),
    OPECEvent(date(2020, 12, 17), "JMMC_25th", "jmmc_with_announcement"),
    # 2021 — gradual normalisation, monthly OPEC+ rhythm
    OPECEvent(date(2021, 1, 5), "OPEC+_13th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 2, 4), "OPEC+_14th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 3, 4), "OPEC+_15th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 4, 1), "OPEC+_16th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 4, 28), "OPEC+_17th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 6, 1), "OPEC_181st_OPEC+_18th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 7, 1), "OPEC+_19th_Ministerial_deadlock", "ministerial"),
    OPECEvent(date(2021, 7, 18), "OPEC+_19th_Ministerial_resumed", "ministerial"),
    OPECEvent(date(2021, 9, 1), "OPEC+_20th_Ministerial", "ministerial"),
    OPECEvent(date(2021, 10, 4), "OPEC+_21st_Ministerial", "ministerial"),
    OPECEvent(date(2021, 11, 4), "OPEC+_22nd_Ministerial", "ministerial"),
    OPECEvent(date(2021, 12, 2), "OPEC+_23rd_Ministerial", "ministerial"),
    # 2022 — Russia invasion + OPEC+ scheduled meetings + October cuts
    OPECEvent(date(2022, 1, 4), "OPEC+_24th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 2, 2), "OPEC+_25th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 3, 2), "OPEC+_26th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 3, 31), "OPEC+_27th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 5, 5), "OPEC+_28th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 6, 2), "OPEC_182nd_OPEC+_29th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 6, 30), "OPEC+_30th_Ministerial", "ministerial"),
    OPECEvent(date(2022, 8, 3), "OPEC+_31st_Ministerial", "ministerial"),
    OPECEvent(date(2022, 9, 5), "OPEC+_32nd_Ministerial", "ministerial"),
    OPECEvent(date(2022, 10, 5), "OPEC+_33rd_Ministerial_2mb_cut", "ministerial"),
    OPECEvent(date(2022, 12, 4), "OPEC+_34th_Ministerial", "ministerial"),
    # 2023 — quarterly cadence + voluntary cuts April + September extension
    OPECEvent(date(2023, 4, 2), "OPEC+_voluntary_cut_announcement", "jmmc_with_announcement"),
    OPECEvent(date(2023, 6, 4), "OPEC+_35th_Ministerial", "ministerial"),
    OPECEvent(date(2023, 7, 6), "Saudi_voluntary_extension_July", "jmmc_with_announcement"),
    OPECEvent(date(2023, 9, 5), "Saudi_Russia_voluntary_extension_Sep", "jmmc_with_announcement"),
    OPECEvent(date(2023, 11, 30), "OPEC+_36th_Ministerial", "ministerial"),
    # 2024 — cuts extension + production hike preparation
    OPECEvent(date(2024, 4, 3), "JMMC_53rd_voluntary_extension", "jmmc_with_announcement"),
    OPECEvent(date(2024, 6, 2), "OPEC+_37th_Ministerial_taper_plan", "ministerial"),
    OPECEvent(date(2024, 9, 5), "OPEC+_taper_delay", "jmmc_with_announcement"),
    OPECEvent(date(2024, 12, 5), "OPEC+_38th_Ministerial_extension", "ministerial"),
    # 2025 — production hikes
    OPECEvent(date(2025, 4, 3), "JMMC_voluntary_hike_announcement", "jmmc_with_announcement"),
    OPECEvent(date(2025, 5, 31), "OPEC+_production_hike_announcement", "jmmc_with_announcement"),
    OPECEvent(date(2025, 7, 5), "OPEC+_production_hike_announcement_2", "jmmc_with_announcement"),
    OPECEvent(date(2025, 9, 7), "OPEC+_voluntary_phase_out_announcement", "jmmc_with_announcement"),
    OPECEvent(date(2025, 11, 2), "OPEC+_December_quota_announcement", "jmmc_with_announcement"),
    OPECEvent(date(2025, 12, 8), "OPEC+_39th_Ministerial", "ministerial"),
    # 2026 — quarterly meetings
    OPECEvent(date(2026, 3, 5), "OPEC+_40th_Ministerial_2026Q1", "ministerial"),
)


def _release_ts_utc(d: date) -> datetime:
    return datetime.combine(d, RELEASE_TIME_CET, tzinfo=VIENNA).astimezone(UTC)


def all_events(
    *,
    since: date | None = None,
    until: date | None = None,
) -> list[OPECEvent]:
    events = list(OPEC_EVENTS)
    if since is not None:
        events = [e for e in events if e.event_date >= since]
    if until is not None:
        events = [e for e in events if e.event_date <= until]
    events.sort(key=lambda e: e.event_date)
    return events


class OPECMinisterialCalendarIngester(BaseIngester):
    """Emit OPEC+ ministerial / JMMC decision events to the PIT store."""

    name = "opec_ministerial_calendar"
    source = "opec"

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
            release_ts = _release_ts_utc(ev.event_date)
            usable_after_ts = release_ts + timedelta(minutes=LATENCY_GUARD_MINUTES)
            data = pd.DataFrame(
                {
                    "event_label": [ev.event_label],
                    "event_type": [ev.event_type],
                    "event_date": [ev.event_date.isoformat()],
                    "release_ts_utc": [release_ts.isoformat()],
                    "usable_after_ts_utc": [usable_after_ts.isoformat()],
                    "frequency": ["irregular"],
                }
            )
            results.append(
                FetchResult(
                    source=self.source,
                    dataset="opec_ministerial",
                    series=ev.event_type,
                    release_ts=release_ts,
                    usable_after_ts=usable_after_ts,
                    revision_ts=None,
                    data=data,
                    provenance={
                        "source": "opec",
                        "method": "curated_calendar_v1.0",
                        "scraper_version": SCRAPER_VERSION,
                        "publisher_url": SOURCE_URL,
                        "event_label": ev.event_label,
                        "event_type": ev.event_type,
                        "event_date": ev.event_date.isoformat(),
                        "completeness_caveat": (
                            "v1.0 covers production-changing announcements only; "
                            "routine technical JMMCs out of scope. Replace with "
                            "live scrape in v1.1."
                        ),
                    },
                    vintage_quality=VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
                    observation_start=ev.event_date,
                    observation_end=ev.event_date,
                )
            )
        return results
