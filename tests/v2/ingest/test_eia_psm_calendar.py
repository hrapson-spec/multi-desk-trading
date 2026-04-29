"""Tests for EIAPSMCalendarIngester."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from v2.ingest.eia_psm_calendar import (
    EIAPSMCalendarIngester,
    _last_friday,
    all_events,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter


@pytest.fixture
def writer_and_manifest(tmp_path: Path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    try:
        yield w, m, tmp_path
    finally:
        m.close()


def test_last_friday_january_2024():
    # Jan 2024 ends on Wed Jan 31; last Friday = Jan 26
    assert _last_friday(2024, 1) == date(2024, 1, 26)


def test_last_friday_when_month_ends_friday():
    # May 2025 ends on Sat May 31 → walk back: May 30 is Friday
    assert _last_friday(2025, 5) == date(2025, 5, 30)


def test_last_friday_december_year_rollover():
    # Dec 2024 ends on Tue Dec 31; last Friday = Dec 27
    assert _last_friday(2024, 12) == date(2024, 12, 27)


def test_all_events_one_per_month():
    events = all_events(since=date(2024, 1, 1), until=date(2024, 12, 31))
    assert len(events) == 12


def test_all_events_post_2020_count():
    events = all_events(since=date(2020, 1, 1), until=date(2026, 4, 29))
    assert 70 <= len(events) <= 80


def test_release_ts_at_1000_eastern():
    events = all_events(since=date(2024, 6, 1), until=date(2024, 6, 30))
    assert len(events) == 1
    et = events[0].release_ts_utc.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    assert et.hour == 10
    assert et.minute == 0


def test_ingest_writes_manifest_rows(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = EIAPSMCalendarIngester(
        w, m, since=date(2024, 1, 1), until=date(2024, 6, 30)
    )
    results = ing.ingest()
    assert len(results) == 6
    rows = m.list_all(source="eia_psm")
    assert len(rows) == 6


def test_dataset_label(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = EIAPSMCalendarIngester(
        w, m, since=date(2024, 6, 1), until=date(2024, 6, 30)
    )
    results = ing.fetch()
    assert results[0].dataset == "psm_calendar"
    assert results[0].series == "psm_release"
    assert results[0].vintage_quality == "release_lag_safe_revision_unknown"
