"""Tests for GPRCalendarIngester."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from v2.ingest.gpr_calendar import GPRCalendarIngester, all_events
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


def test_all_events_friday_only():
    events = all_events(since=date(2024, 1, 1), until=date(2024, 1, 31))
    for ev in events:
        # Friday weekday() == 4
        assert ev.week_friday.weekday() == 4


def test_all_events_weekly_spacing():
    events = all_events(since=date(2024, 1, 1), until=date(2024, 12, 31))
    fridays = [ev.week_friday for ev in events]
    for i in range(1, len(fridays)):
        assert (fridays[i] - fridays[i - 1]).days == 7


def test_all_events_post_2020_count():
    events = all_events(since=date(2020, 1, 1), until=date(2026, 4, 29))
    # ~6.3 years × 52 weeks/year = ~327 weekly events
    assert 320 <= len(events) <= 340


def test_ingest_writes_manifest_rows(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = GPRCalendarIngester(
        w, m, since=date(2024, 1, 1), until=date(2024, 1, 31)
    )
    results = ing.ingest()
    assert len(results) >= 4  # 4 Fridays in Jan 2024
    rows = m.list_all(source="caldara_iacoviello")
    assert len(rows) == len(results)


def test_dataset_and_series_labels(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = GPRCalendarIngester(w, m, since=date(2024, 6, 1), until=date(2024, 6, 7))
    results = ing.fetch()
    assert results[0].dataset == "gpr_weekly"
    assert results[0].series == "gpr_weekly_release"
    assert results[0].vintage_quality == "release_lag_safe_revision_unknown"
