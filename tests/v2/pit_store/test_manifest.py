"""Manifest-layer tests. No Parquet I/O; just the DuckDB-backed manifest API."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from v2.pit_store.manifest import ManifestRow, new_manifest_id, open_manifest


@pytest.fixture
def manifest(tmp_path):
    with open_manifest(tmp_path) as m:
        yield m


def _row(**overrides) -> ManifestRow:
    base: dict = {
        "manifest_id": new_manifest_id(),
        "source": "eia_wpsr",
        "series": "crude_stocks",
        "release_ts": datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        "revision_ts": None,
        "observation_start": date(2026, 1, 3),
        "observation_end": date(2026, 1, 9),
        "schema_hash": "schema_x",
        "row_count": 1,
        "checksum": "cs1",
        "ingest_ts": datetime(2026, 1, 14, 16, 0, tzinfo=UTC),
        "provenance": {"source": "eia.gov", "method": "http"},
        "parquet_path": (
            "raw/eia_wpsr/series=crude_stocks/release_ts=2026-01-14T15-30-00Z/data.parquet"
        ),
        "superseded_by": None,
    }
    base.update(overrides)
    return ManifestRow(**base)


def test_insert_and_roundtrip(manifest):
    r = _row()
    manifest.insert(r)
    got = manifest.get(r.manifest_id)
    assert got is not None
    assert got.source == r.source
    assert got.series == r.series
    assert got.release_ts == r.release_ts
    assert got.checksum == r.checksum
    assert got.provenance == {"source": "eia.gov", "method": "http"}


def test_manifest_allows_duplicate_null_revision_at_db_layer(manifest):
    # DuckDB treats NULLs as distinct in UNIQUE indexes. Uniqueness of the
    # first-release slot is enforced by PITWriter, not by the manifest.
    # This test pins that the manifest itself does NOT enforce it — any
    # change to DB-level uniqueness must update PITWriter accordingly.
    r1 = _row()
    r2 = _row(manifest_id=new_manifest_id(), checksum="cs2")
    manifest.insert(r1)
    manifest.insert(r2)
    assert len(manifest.list_all()) == 2


def test_different_revision_ts_allowed(manifest):
    r1 = _row()
    r2 = _row(
        manifest_id=new_manifest_id(),
        revision_ts=datetime(2026, 1, 21, 15, 30, tzinfo=UTC),
        checksum="cs2",
    )
    manifest.insert(r1)
    manifest.insert(r2)  # different revision_ts ⇒ distinct slot
    rows = manifest.list_all()
    assert len(rows) == 2


def test_supersede(manifest):
    old = _row()
    new = _row(
        manifest_id=new_manifest_id(),
        revision_ts=datetime(2026, 1, 21, 15, 30, tzinfo=UTC),
        checksum="cs2",
    )
    manifest.insert(old)
    manifest.insert(new)
    manifest.supersede(old.manifest_id, new.manifest_id)
    got = manifest.get(old.manifest_id)
    assert got is not None
    assert got.superseded_by == new.manifest_id


def test_find_first_release_isolates_null_revision(manifest):
    first = _row()
    revised = _row(
        manifest_id=new_manifest_id(),
        revision_ts=datetime(2026, 1, 21, 15, 30, tzinfo=UTC),
        checksum="cs2",
    )
    manifest.insert(first)
    manifest.insert(revised)
    got = manifest.find_first_release(
        "eia_wpsr", "crude_stocks", datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    )
    assert got is not None
    assert got.manifest_id == first.manifest_id
    assert got.revision_ts is None


def test_null_series_handling(manifest):
    r = _row(
        series=None,
        parquet_path="raw/some_source/release_ts=2026-01-14T15-30-00Z/data.parquet",
    )
    manifest.insert(r)
    got = manifest.find_first_release(r.source, None, r.release_ts)
    assert got is not None
    assert got.series is None
