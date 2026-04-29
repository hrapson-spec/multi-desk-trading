"""Writer tests: Parquet + manifest + checksum + revision handling."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd
import pytest

from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITChecksumMismatch, PITWriter


def _df_a() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period_end": [date(2026, 1, 9), date(2026, 1, 9)],
            "series": ["crude_stocks", "gasoline_stocks"],
            "value": [425_000.0, 245_000.0],
        }
    )


def _df_b() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period_end": [date(2026, 1, 9), date(2026, 1, 9)],
            "series": ["crude_stocks", "gasoline_stocks"],
            "value": [427_500.0, 245_000.0],  # crude revised upward
        }
    )


@pytest.fixture
def writer_and_manifest(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    try:
        yield w, m
    finally:
        m.close()


def test_first_release_writes_parquet_and_manifest(writer_and_manifest, tmp_path):
    w, m = writer_and_manifest
    r = w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        data=_df_a(),
        provenance={"source": "eia.gov", "method": "http_scrape", "scraper_version": "0.1"},
        observation_start=date(2026, 1, 3),
        observation_end=date(2026, 1, 9),
    )
    assert r.was_revision is False
    assert r.superseded_manifest_id is None
    assert r.row_count == 2
    assert r.vintage_quality == "true_first_release"
    assert (tmp_path / r.parquet_path).exists()
    mf = m.get(r.manifest_id)
    assert mf is not None
    assert mf.checksum == r.checksum
    assert mf.revision_ts is None
    assert mf.row_count == 2
    assert mf.vintage_quality == "true_first_release"


def test_write_records_dataset_and_vintage_quality(writer_and_manifest, tmp_path):
    w, m = writer_and_manifest
    r = w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        data=pd.DataFrame({"value": [425_000.0]}),
        provenance={"source": "eia.gov", "method": "archive_csv"},
        vintage_quality="release_lag_safe_revision_unknown",
    )
    assert r.dataset == "wpsr"
    assert r.vintage_quality == "release_lag_safe_revision_unknown"
    assert (tmp_path / r.parquet_path).exists()
    mf = m.get(r.manifest_id)
    assert mf is not None
    assert mf.source == "eia"
    assert mf.dataset == "wpsr"
    assert mf.series == "WCESTUS1"
    assert mf.vintage_quality == "release_lag_safe_revision_unknown"


def test_reingest_identical_payload_is_idempotent(writer_and_manifest):
    w, m = writer_and_manifest
    kw: dict = {
        "source": "eia_wpsr",
        "series": "weekly",
        "release_ts": datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        "provenance": {"source": "eia.gov", "method": "http_scrape"},
    }
    r1 = w.write_vintage(data=_df_a(), **kw)
    r2 = w.write_vintage(data=_df_a(), **kw)
    assert r1.manifest_id == r2.manifest_id
    assert r1.checksum == r2.checksum
    # Only one row should exist at this slot.
    rows = m.list_all("eia_wpsr")
    assert len(rows) == 1


def test_reingest_different_payload_is_revision(writer_and_manifest):
    w, m = writer_and_manifest
    release_ts = datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    r1 = w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=release_ts,
        data=_df_a(),
        provenance={"source": "eia.gov", "method": "http_scrape"},
    )
    r2 = w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=release_ts,
        data=_df_b(),
        provenance={"source": "eia.gov", "method": "http_scrape"},
    )
    assert r2.was_revision is True
    assert r2.superseded_manifest_id == r1.manifest_id
    first = m.get(r1.manifest_id)
    assert first is not None
    assert first.superseded_by == r2.manifest_id
    revision = m.get(r2.manifest_id)
    assert revision is not None
    assert revision.revision_ts is not None


def test_same_release_ts_different_observation_period_is_not_revision(writer_and_manifest):
    w, m = writer_and_manifest
    release_ts = datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    first = w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts,
        data=pd.DataFrame({"value": [425_000.0]}),
        provenance={"source": "eia.gov", "method": "archive_csv"},
        observation_start=date(2026, 1, 3),
        observation_end=date(2026, 1, 9),
    )
    second = w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts,
        data=pd.DataFrame({"value": [430_000.0]}),
        provenance={"source": "eia.gov", "method": "archive_csv"},
        observation_start=date(2026, 1, 10),
        observation_end=date(2026, 1, 16),
    )

    assert first.was_revision is False
    assert second.was_revision is False
    assert first.manifest_id != second.manifest_id
    assert first.parquet_path != second.parquet_path
    rows = m.list_all("eia", dataset="wpsr")
    assert len(rows) == 2
    assert {row.observation_end for row in rows} == {
        date(2026, 1, 9),
        date(2026, 1, 16),
    }


def test_reingest_with_explicit_revision_ts_does_not_collide(writer_and_manifest):
    w, m = writer_and_manifest
    release_ts = datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    rev_ts = datetime(2026, 1, 21, 15, 30, tzinfo=UTC)
    r1 = w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=release_ts,
        data=_df_a(),
        provenance={"source": "eia.gov", "method": "http"},
    )
    r2 = w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=release_ts,
        revision_ts=rev_ts,
        data=_df_b(),
        provenance={"source": "eia.gov", "method": "http"},
    )
    # Second write is a revision with explicit revision_ts.
    assert r2.was_revision is True
    rev_row = m.get(r2.manifest_id)
    assert rev_row is not None
    assert rev_row.revision_ts == rev_ts
    # Re-ingesting the SAME (release_ts, revision_ts) with identical data is idempotent.
    r3 = w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=release_ts,
        revision_ts=rev_ts,
        data=_df_b(),
        provenance={"source": "eia.gov", "method": "http"},
    )
    assert r3.manifest_id == r2.manifest_id
    # Re-ingesting the same slot with DIFFERENT data raises PITChecksumMismatch.
    with pytest.raises(PITChecksumMismatch):
        w.write_vintage(
            source="eia_wpsr",
            series="weekly",
            release_ts=release_ts,
            revision_ts=rev_ts,
            data=_df_a(),  # different payload under the same (release_ts, revision_ts)
            provenance={"source": "eia.gov", "method": "http"},
        )
    # Unrelated: r1 is still marked superseded by r2.
    first = m.get(r1.manifest_id)
    assert first is not None
    assert first.superseded_by == r2.manifest_id


def test_provenance_required_keys(writer_and_manifest):
    w, _ = writer_and_manifest
    with pytest.raises(ValueError):
        w.write_vintage(
            source="eia_wpsr",
            series="weekly",
            release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
            data=_df_a(),
            provenance={"source": "eia.gov"},  # missing 'method'
        )


def test_empty_dataframe_rejected(writer_and_manifest):
    w, _ = writer_and_manifest
    with pytest.raises(ValueError):
        w.write_vintage(
            source="eia_wpsr",
            series="weekly",
            release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
            data=pd.DataFrame(),
            provenance={"source": "eia.gov", "method": "http"},
        )
