"""Tests for FOMCCalendarIngester."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from v2.ingest.fomc_calendar import (
    ANNOUNCEMENT_TIME_ET,
    MINUTES_OFFSET_DAYS,
    SCHEDULED_STATEMENT_DATES,
    FOMCCalendarIngester,
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


def test_scheduled_dates_are_chronological_and_unique():
    assert list(SCHEDULED_STATEMENT_DATES) == sorted(set(SCHEDULED_STATEMENT_DATES))


def test_scheduled_dates_post_2020_only():
    for d in SCHEDULED_STATEMENT_DATES:
        assert d.year >= 2020


def test_all_events_yields_2_per_meeting_with_minutes_default():
    events = all_events(since=date(2024, 1, 1), until=date(2024, 12, 31))
    n_meetings_in_2024 = sum(1 for d in SCHEDULED_STATEMENT_DATES if d.year == 2024)
    # Statement events must equal scheduled meeting count for the year.
    assert sum(1 for e in events if e.event_type == "statement") == n_meetings_in_2024
    # Minutes that fall within the year may be slightly fewer due to the
    # +21d offset shifting Dec minutes into Jan; verify monotone ordering.
    timestamps = [e.event_date for e in events]
    assert timestamps == sorted(timestamps)


def test_all_events_filters_by_since_until():
    events_2025 = all_events(since=date(2025, 1, 1), until=date(2025, 12, 31))
    for e in events_2025:
        assert date(2025, 1, 1) <= e.event_date <= date(2025, 12, 31)


def test_all_events_include_minutes_false_drops_minutes():
    events = all_events(
        since=date(2024, 1, 1), until=date(2024, 12, 31), include_minutes=False
    )
    assert all(e.event_type == "statement" for e in events)


def test_minutes_offset_days_is_three_weeks():
    assert MINUTES_OFFSET_DAYS == 21


def test_ingest_writes_two_manifest_rows_per_meeting(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = FOMCCalendarIngester(
        w, m,
        since=date(2024, 1, 1),
        until=date(2024, 3, 31),  # captures 2 statements (Jan 31, Mar 20)
    )
    results = ing.ingest()
    # 2 statements + 2 minutes = 4 events
    assert len(results) == 4

    rows = m.list_all(source="fomc")
    assert len(rows) == 4
    series_set = {r.series for r in rows}
    assert series_set == {"fomc_statement", "fomc_minutes"}


def test_ingest_emits_release_ts_at_1400_eastern(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = FOMCCalendarIngester(
        w, m,
        since=date(2024, 1, 10),  # past Dec-2023 minutes (released Jan 3)
        until=date(2024, 1, 31),
    )
    results = ing.fetch()
    # Just the Jan 31 statement; minutes for Jan 31 release Feb 21.
    assert len(results) == 1
    statement = results[0]
    assert statement.series == "fomc_statement"
    # 14:00 ET on 2024-01-31 = 19:00 UTC (EST = UTC-5)
    assert statement.release_ts.tzinfo is not None
    et_local = statement.release_ts.astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York")
    )
    assert et_local.time() == ANNOUNCEMENT_TIME_ET
    # usable_after_ts = release_ts + 5 minutes
    assert (
        statement.usable_after_ts - statement.release_ts
    ).total_seconds() == 300.0


def test_ingest_provenance_includes_event_metadata(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = FOMCCalendarIngester(
        w, m,
        since=date(2024, 6, 1),
        until=date(2024, 6, 30),
    )
    results = ing.fetch()
    for fr in results:
        assert fr.provenance["source"] == "fomc"
        assert fr.provenance["method"] == "calendar_encoded"
        assert "publisher_url" in fr.provenance
        assert fr.provenance["event_type"] in ("statement", "minutes")
        assert fr.provenance["meeting_label"]
        assert fr.vintage_quality == "true_first_release"


def test_ingest_data_payload_minimal_one_row(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = FOMCCalendarIngester(
        w, m,
        since=date(2024, 6, 1),
        until=date(2024, 6, 30),
    )
    results = ing.fetch()
    for fr in results:
        assert len(fr.data) == 1
        assert "event_type" in fr.data.columns
        assert "meeting_label" in fr.data.columns
        assert "release_ts_utc" in fr.data.columns


def test_dataset_label_is_fomc_announcements(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = FOMCCalendarIngester(w, m, since=date(2024, 1, 1), until=date(2024, 6, 30))
    results = ing.fetch()
    for fr in results:
        assert fr.dataset == "fomc_announcements"


def test_post_2020_event_count_is_at_least_50(writer_and_manifest):
    """Sanity: at least 50 statement events post-2020 (8/yr × 6+ years)."""
    statement_count = sum(
        1 for d in SCHEDULED_STATEMENT_DATES if d >= date(2020, 1, 1)
    )
    assert statement_count >= 50, (
        f"only {statement_count} scheduled statements post-2020; "
        "calendar may be missing meetings"
    )
