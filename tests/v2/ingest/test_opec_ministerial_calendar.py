"""Tests for OPECMinisterialCalendarIngester."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from v2.ingest.opec_ministerial_calendar import (
    OPEC_EVENTS,
    OPECMinisterialCalendarIngester,
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


def test_events_are_post_2020_only():
    for ev in OPEC_EVENTS:
        assert ev.event_date.year >= 2020


def test_events_are_chronological_and_unique():
    dates = [e.event_date for e in OPEC_EVENTS]
    assert dates == sorted(dates), "OPEC_EVENTS not chronological"
    # Multiple events on same date are allowed in principle but should be rare;
    # current curated list has no duplicates.
    assert len(set(dates)) == len(dates), "duplicate dates in curated list"


def test_event_types_are_valid():
    valid = {"ministerial", "jmmc_with_announcement", "ordinary_conference"}
    for ev in OPEC_EVENTS:
        assert ev.event_type in valid, (
            f"unknown event_type {ev.event_type!r} on {ev.event_date}"
        )


def test_curated_list_size():
    """Sanity: 40-60 events post-2020 covering OPEC+ era."""
    assert 40 <= len(OPEC_EVENTS) <= 60, (
        f"unexpected curated event count: {len(OPEC_EVENTS)}"
    )


def test_all_events_filters_by_since_until():
    e = all_events(since=date(2022, 1, 1), until=date(2022, 12, 31))
    for ev in e:
        assert date(2022, 1, 1) <= ev.event_date <= date(2022, 12, 31)


def test_ingest_writes_one_manifest_row_per_event(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = OPECMinisterialCalendarIngester(
        w, m,
        since=date(2022, 1, 1),
        until=date(2022, 6, 30),
    )
    results = ing.ingest()
    expected_count = len(
        all_events(since=date(2022, 1, 1), until=date(2022, 6, 30))
    )
    assert len(results) == expected_count
    rows = m.list_all(source="opec")
    assert len(rows) == expected_count


def test_release_ts_at_1400_vienna(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = OPECMinisterialCalendarIngester(
        w, m, since=date(2022, 6, 1), until=date(2022, 6, 30)
    )
    results = ing.fetch()
    assert len(results) >= 1
    et = results[0].release_ts.astimezone(
        __import__("zoneinfo").ZoneInfo("Europe/Vienna")
    )
    assert et.hour == 14
    assert et.minute == 0


def test_latency_guard_30_minutes(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = OPECMinisterialCalendarIngester(
        w, m, since=date(2022, 6, 1), until=date(2022, 6, 30)
    )
    results = ing.fetch()
    for fr in results:
        delta = (fr.usable_after_ts - fr.release_ts).total_seconds()
        assert delta == 30.0 * 60.0, "expected 30-minute OPEC latency guard"


def test_vintage_quality_v1_is_release_lag_safe(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = OPECMinisterialCalendarIngester(
        w, m, since=date(2022, 6, 1), until=date(2022, 6, 30)
    )
    results = ing.fetch()
    for fr in results:
        assert fr.vintage_quality == "release_lag_safe_revision_unknown"


def test_provenance_includes_completeness_caveat(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = OPECMinisterialCalendarIngester(
        w, m, since=date(2022, 6, 1), until=date(2022, 6, 30)
    )
    results = ing.fetch()
    for fr in results:
        assert "completeness_caveat" in fr.provenance
        assert "v1.1" in fr.provenance["completeness_caveat"]


def test_dataset_label_is_opec_ministerial(writer_and_manifest):
    w, m, _ = writer_and_manifest
    ing = OPECMinisterialCalendarIngester(
        w, m, since=date(2022, 6, 1), until=date(2022, 6, 30)
    )
    results = ing.fetch()
    for fr in results:
        assert fr.dataset == "opec_ministerial"
