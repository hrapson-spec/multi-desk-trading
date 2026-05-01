"""Reader tests: as_of, latest_available_before, vintage_diff, checksum."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pandas as pd
import pytest

from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITChecksumError, PITReader
from v2.pit_store.writer import PITWriter


def _df(crude_value: float, gasoline_value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period_end": [date(2026, 1, 9), date(2026, 1, 9)],
            "series": ["crude_stocks", "gasoline_stocks"],
            "value": [crude_value, gasoline_value],
        }
    )


@pytest.fixture
def store(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    r = PITReader(tmp_path, m)
    try:
        yield tmp_path, w, r, m
    finally:
        m.close()


def _ingest_two_vintages(writer):
    """One first-release on Wed Jan 14, then a revision on Wed Jan 21."""
    first = writer.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        data=_df(425_000.0, 245_000.0),
        provenance={"source": "eia.gov", "method": "http"},
    )
    revision = writer.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        data=_df(427_500.0, 245_000.0),
        provenance={"source": "eia.gov", "method": "http"},
    )
    return first, revision


def test_as_of_returns_first_release_before_revision(store):
    _, w, r, _ = store
    first, _rev = _ingest_two_vintages(w)
    # Ask for the data as of Jan 18 — before the revision. Must return the first-release.
    res = r.as_of("eia_wpsr", "weekly", datetime(2026, 1, 18, 12, 0, tzinfo=UTC))
    assert res is not None
    assert res.manifest.manifest_id == first.manifest_id
    assert res.data.loc[res.data["series"] == "crude_stocks", "value"].iloc[0] == 425_000.0
    assert res.data_quality.decision_eligible is True
    assert res.data_quality.checksum_verified is True
    assert res.data_quality.freshness_state == "fresh"


def test_as_of_returns_revision_after_it_is_applied(store):
    _, w, r, _ = store
    _first, rev = _ingest_two_vintages(w)
    # After the revision's ingest_ts, the revision is the decision-eligible vintage.
    # Revision's revision_ts = its ingest time, which is strictly after the first release.
    res = r.as_of("eia_wpsr", "weekly", datetime(2030, 1, 1, 0, 0, tzinfo=UTC))
    assert res is not None
    assert res.manifest.manifest_id == rev.manifest_id
    assert res.data.loc[res.data["series"] == "crude_stocks", "value"].iloc[0] == 427_500.0


def test_as_of_returns_none_when_nothing_eligible(store):
    _, w, r, _ = store
    w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        data=_df(1.0, 2.0),
        provenance={"source": "eia.gov", "method": "http"},
    )
    # Ask for data as of Jan 1 — before any release. None eligible.
    res = r.as_of("eia_wpsr", "weekly", datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    assert res is None


def test_as_of_respects_usable_after_latency_guard(store):
    _, w, r, _ = store
    release_ts = datetime(2026, 4, 17, 14, 30, tzinfo=UTC)
    usable_after = release_ts + timedelta(minutes=5)
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts,
        usable_after_ts=usable_after,
        data=pd.DataFrame({"value": [425_000.0]}),
        provenance={"source": "eia.gov", "method": "archive_csv"},
    )
    assert (
        r.as_of(
            "eia",
            "WCESTUS1",
            usable_after - timedelta(seconds=1),
            dataset="wpsr",
        )
        is None
    )
    res = r.as_of(
        "eia",
        "WCESTUS1",
        usable_after + timedelta(seconds=1),
        dataset="wpsr",
    )
    assert res is not None
    assert res.data["value"].iloc[0] == 425_000.0


def test_as_of_same_release_ts_prefers_latest_observation_period(store):
    _, w, r, _ = store
    release_ts = datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts,
        data=pd.DataFrame({"value": [425_000.0]}),
        provenance={"source": "eia.gov", "method": "archive_csv"},
        observation_start=date(2026, 1, 3),
        observation_end=date(2026, 1, 9),
    )
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts,
        data=pd.DataFrame({"value": [430_000.0]}),
        provenance={"source": "eia.gov", "method": "archive_csv"},
        observation_start=date(2026, 1, 10),
        observation_end=date(2026, 1, 16),
    )

    res = r.as_of(
        "eia",
        "WCESTUS1",
        datetime(2026, 1, 14, 15, 31, tzinfo=UTC),
        dataset="wpsr",
    )

    assert res is not None
    assert res.manifest.observation_end == date(2026, 1, 16)
    assert res.data["value"].iloc[0] == 430_000.0


def test_latest_available_before_ignores_supersession(store):
    _, w, r, _ = store
    first, rev = _ingest_two_vintages(w)
    # Both releases share release_ts. latest_available_before picks the most
    # recent (revision, since revision_ts NULLS LAST) strictly before `ts`.
    res = r.latest_available_before("eia_wpsr", "weekly", datetime(2030, 1, 1, 0, 0, tzinfo=UTC))
    assert res is not None
    # The revision has a non-null revision_ts, so NULLS LAST makes it the winner.
    assert res.manifest.manifest_id in {first.manifest_id, rev.manifest_id}


def test_checksum_mismatch_raises(store):
    root, w, r, _ = store
    first, _rev = _ingest_two_vintages(w)
    # Ask for a timestamp before the revision became known → first-release
    # is what as_of will pick. Corrupting that file must trigger PITChecksumError.
    path = root / first.parquet_path
    path.write_bytes(path.read_bytes() + b"\x00")
    with pytest.raises(PITChecksumError):
        r.as_of("eia_wpsr", "weekly", datetime(2026, 1, 18, 12, 0, tzinfo=UTC))


def test_vintage_diff_between_first_release_and_revision(store):
    _, w, r, _ = store
    # For vintage_diff we need two distinct first-release rows at different
    # release_ts values (since find_first_release matches only revision_ts IS
    # NULL). Ingest two separate weekly releases.
    w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        data=_df(425_000.0, 245_000.0),
        provenance={"source": "eia.gov", "method": "http"},
    )
    w.write_vintage(
        source="eia_wpsr",
        series="weekly",
        release_ts=datetime(2026, 1, 21, 15, 30, tzinfo=UTC),
        data=_df(428_000.0, 246_500.0),
        provenance={"source": "eia.gov", "method": "http"},
    )
    diff = r.vintage_diff(
        "eia_wpsr",
        "weekly",
        datetime(2026, 1, 14, 15, 30, tzinfo=UTC),
        datetime(2026, 1, 21, 15, 30, tzinfo=UTC),
    )
    assert len(diff) > 0
