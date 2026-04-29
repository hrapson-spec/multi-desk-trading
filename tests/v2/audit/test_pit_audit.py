"""Layer-1 PIT audit tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from v2.audit.pit_audit import PITAuditor
from v2.pit_store.manifest import open_manifest
from v2.pit_store.release_calendar import load_calendar
from v2.pit_store.writer import PITWriter

PROJECT_CALENDARS = Path(__file__).resolve().parents[3] / "v2" / "pit_store" / "calendars"


@pytest.fixture
def store_and_calendars(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    calendars = {}
    for p in PROJECT_CALENDARS.glob("*.yaml"):
        c = load_calendar(p)
        calendars[c.source] = c
    try:
        yield tmp_path, w, m, calendars
    finally:
        m.close()


def _df():
    return pd.DataFrame({"value": [1.0, 2.0]})


def _ingest(w, source, release_ts, *, dataset=None):
    w.write_vintage(
        source=source,
        dataset=dataset,
        series="main",
        release_ts=release_ts,
        data=_df(),
        provenance={"source": source, "method": "test"},
    )


def test_audit_empty_manifest_flags_issue(store_and_calendars):
    root, _w, m, calendars = store_and_calendars
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit()
    assert not report.is_clean
    assert any("empty" in i.lower() for i in report.issues)


def test_audit_reports_per_source_stats(store_and_calendars):
    root, w, m, calendars = store_and_calendars
    _ingest(w, "eia", datetime(2026, 1, 14, 15, 30, tzinfo=UTC), dataset="wpsr")
    _ingest(w, "eia", datetime(2026, 1, 21, 15, 30, tzinfo=UTC), dataset="wpsr")
    _ingest(w, "cftc_cot", datetime(2026, 1, 16, 20, 30, tzinfo=UTC))
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit()
    assert report.is_clean, report.issues
    assert report.sources["eia"].vintage_count == 2
    assert report.sources["cftc_cot"].vintage_count == 1
    assert report.sources["eia"].calendar_present is True


def test_audit_flags_missing_calendar(store_and_calendars):
    root, w, m, calendars = store_and_calendars
    _ingest(w, "made_up_source", datetime(2026, 1, 14, 15, 30, tzinfo=UTC))
    # Drop the calendar for the made-up source.
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit()
    assert not report.is_clean
    assert any("made_up_source" in i for i in report.issues)


def test_audit_flags_missing_required_source(store_and_calendars):
    root, w, m, calendars = store_and_calendars
    _ingest(w, "eia", datetime(2026, 1, 14, 15, 30, tzinfo=UTC), dataset="wpsr")
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit(feature_requirements={"crude_stocks": "cftc_cot"})
    assert not report.is_clean
    assert any("cftc_cot" in i for i in report.issues)


def test_audit_training_window_earliest(store_and_calendars):
    root, w, m, calendars = store_and_calendars
    _ingest(w, "eia", datetime(2025, 1, 14, 15, 30, tzinfo=UTC), dataset="wpsr")
    _ingest(w, "eia", datetime(2026, 1, 14, 15, 30, tzinfo=UTC), dataset="wpsr")
    _ingest(w, "cftc_cot", datetime(2024, 6, 21, 20, 30, tzinfo=UTC))
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit()
    # Training window = latest of first-release across all sources
    # = 2025-01-14 (eia's earliest), since cftc's earliest is 2024-06-21
    # and eia's earliest is 2025-01-14.
    assert report.earliest_reconstructible_as_of == datetime(2025, 1, 14, 15, 30, tzinfo=UTC)


def test_audit_detects_checksum_failure(store_and_calendars):
    root, w, m, calendars = store_and_calendars
    _ingest(w, "eia", datetime(2026, 1, 14, 15, 30, tzinfo=UTC), dataset="wpsr")
    # Corrupt the on-disk Parquet.
    for p in root.rglob("*.parquet"):
        p.write_bytes(p.read_bytes() + b"\x00")
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit()
    assert not report.is_clean
    assert report.sources["eia"].checksum_failures == 1
    assert any("checksum" in i.lower() for i in report.issues)


def test_audit_report_serialises_to_json(store_and_calendars):
    root, w, m, calendars = store_and_calendars
    _ingest(w, "eia", datetime(2026, 1, 14, 15, 30, tzinfo=UTC), dataset="wpsr")
    auditor = PITAuditor(root, m, calendars)
    report = auditor.audit()
    js = report.to_json()
    assert "generated_at" in js
    assert "sources" in js
    assert js["is_clean"] is True
