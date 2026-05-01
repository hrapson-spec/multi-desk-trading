"""Tests for EIASTEOCalendarIngester."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from v2.ingest.eia_steo_calendar import (
    RELEASE_DATE_OVERRIDES,
    EIASTEOCalendarIngester,
    _release_date_for,
    _second_tuesday,
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


def test_second_tuesday_january_2024():
    # January 2024: 1=Mon, so 1st Tue = Jan 2, 2nd Tue = Jan 9
    assert _second_tuesday(2024, 1) == date(2024, 1, 9)


def test_second_tuesday_with_first_day_being_tuesday():
    # March 2024: 1=Fri, so 1st Tue = Mar 5, 2nd Tue = Mar 12
    assert _second_tuesday(2024, 3) == date(2024, 3, 12)


def test_april_2020_uses_override():
    assert _release_date_for(2020, 4) == date(2020, 4, 7)
    assert (2020, 4) in RELEASE_DATE_OVERRIDES


def test_typical_month_uses_2nd_tuesday():
    assert _release_date_for(2024, 6) == date(2024, 6, 11)


def test_all_events_one_per_month_in_range():
    events = all_events(since=date(2024, 1, 1), until=date(2024, 12, 31))
    assert len(events) == 12
    seen_months = {(e.issue_year, e.issue_month) for e in events}
    assert len(seen_months) == 12


def test_all_events_post_2020_event_count_consistent():
    events = all_events(since=date(2020, 1, 1), until=date(2026, 4, 29))
    # ~76 monthly events expected (Jan 2020 - Apr 2026 = ~76 months)
    assert 70 <= len(events) <= 80, f"got {len(events)} STEO events"


def test_all_events_chronological():
    events = all_events(since=date(2024, 1, 1), until=date(2024, 12, 31))
    dates = [e.release_date for e in events]
    assert dates == sorted(dates)


def test_release_ts_at_noon_eastern():
    events = all_events(since=date(2024, 6, 1), until=date(2024, 6, 30))
    assert len(events) == 1
    et = events[0].release_ts_utc.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    assert et.hour == 12
    assert et.minute == 0


def test_ingest_writes_one_manifest_row_per_event(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = EIASTEOCalendarIngester(
        w, m,
        since=date(2024, 1, 1),
        until=date(2024, 6, 30),
    )
    results = ing.ingest()
    assert len(results) == 6
    rows = m.list_all(source="eia_steo")
    rows_steo = [r for r in rows if r.dataset == "steo_calendar"]
    assert len(rows_steo) == 6


def test_ingest_vintage_quality_is_release_lag_safe(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = EIASTEOCalendarIngester(
        w, m, since=date(2024, 6, 1), until=date(2024, 6, 30)
    )
    results = ing.fetch()
    for fr in results:
        # v1.0: dates computed from rule, not scraped, so quality is degraded
        assert fr.vintage_quality == "release_lag_safe_revision_unknown"


def test_ingest_provenance_marks_overrides(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = EIASTEOCalendarIngester(
        w, m,
        since=date(2020, 4, 1),
        until=date(2020, 4, 30),
    )
    results = ing.fetch()
    assert len(results) == 1
    assert results[0].provenance["had_override"] is True
    assert results[0].provenance["release_date"] == "2020-04-07"


def test_ingest_dataset_label(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = EIASTEOCalendarIngester(
        w, m, since=date(2024, 6, 1), until=date(2024, 6, 30)
    )
    results = ing.fetch()
    assert results[0].dataset == "steo_calendar"
    assert results[0].series == "steo_release"
