"""PIT leakage gate for the public-data feature join.

This is the rights-and-leakage guardrail. It uses real ``PITWriter``,
real ``PITManifest``, and real ``PITReader.as_of`` — no mocks. If
``build_features`` reimplements eligibility (e.g. inspects
``observation_date``) the test fails: that's by design.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from v2.ingest.public_feature_join import build_features
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter

NY = ZoneInfo("America/New_York")


@pytest.fixture
def store(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    r = PITReader(tmp_path, m)
    try:
        yield tmp_path, w, r, m
    finally:
        m.close()


def _eia_vintage(value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": [date(2026, 4, 17)],
            "value": [value],
        }
    )


def _cot_vintage(value: float) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "period": [date(2026, 4, 21)],
            "value": [value],
        }
    )


def test_eia_pre_release_is_absent_post_release_present(store, tmp_path):
    """Canonical leak class: WPSR week-ending Friday 2026-04-17 is observed
    Friday — but its release_ts is Wednesday 2026-04-22 11:00 ET. At
    Wednesday 10:00 ET (pre-release), the value MUST NOT be visible
    even though the observation date is in the past."""
    _, w, r, m = store
    release_ts_utc = datetime(2026, 4, 22, 11, 0, tzinfo=NY).astimezone(UTC)
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts_utc,
        data=_eia_vintage(440000.0),
        provenance={"source": "eia.gov", "method": "test"},
    )
    out = tmp_path / "features_pre.parquet"
    df_pre = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=datetime(2026, 4, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 4, 22, 14, 0, tzinfo=UTC),  # 14:00 UTC = 10:00 ET
        output_path=out,
    )
    col = "eia__wpsr__WCESTUS1__value"
    assert col in df_pre.columns
    # The Wednesday 2026-04-22 row at the daily grid is the 10:00 ET snapshot
    # because the daily grid is rendered at the start of `start`+N days.
    # All pre-release rows must be NaN.
    pre_mask = df_pre.index < pd.Timestamp(release_ts_utc)
    assert df_pre.loc[pre_mask, col].isna().all(), (
        "PIT leak: a pre-release EIA value is visible to the feature join. "
        "The eligibility check must respect release_ts."
    )

    # Now extend past the release.
    out2 = tmp_path / "features_post.parquet"
    df_post = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=datetime(2026, 4, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 4, 23, 0, 0, tzinfo=UTC),
        output_path=out2,
    )
    # Strictly after release, the value must be visible.
    post_mask = df_post.index > pd.Timestamp(release_ts_utc)
    assert (df_post.loc[post_mask, col] == 440000.0).all()


def test_cftc_pre_release_absent_post_present(store, tmp_path):
    _, w, r, m = store
    # 2026-04-24 is a Friday.
    release_ts_utc = datetime(2026, 4, 24, 15, 30, tzinfo=NY).astimezone(UTC)
    w.write_vintage(
        source="cftc",
        series="067651",
        release_ts=release_ts_utc,
        data=_cot_vintage(1234.0),
        provenance={"source": "cftc.gov", "method": "test"},
    )
    # Pre-release (Fri 15:00 ET = 19:00 UTC). Use end well before release_ts.
    out = tmp_path / "cot_pre.parquet"
    df_pre = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
        end=datetime(2026, 4, 24, 19, 0, tzinfo=UTC),  # 15:00 ET
        output_path=out,
    )
    col = "cftc__067651__value"
    assert col in df_pre.columns
    pre_mask = df_pre.index < pd.Timestamp(release_ts_utc)
    assert df_pre.loc[pre_mask, col].isna().all()

    # Post-release: extend by an hour.
    out2 = tmp_path / "cot_post.parquet"
    df_post = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=datetime(2026, 4, 22, 0, 0, tzinfo=UTC),
        end=datetime(2026, 4, 25, 0, 0, tzinfo=UTC),  # well after 15:30 ET
        output_path=out2,
    )
    post_mask = df_post.index > pd.Timestamp(release_ts_utc)
    assert (df_post.loc[post_mask, col] == 1234.0).all()


def test_revision_rewinds_value(store, tmp_path):
    """First-release at T1 with value=100; revision at T2 with value=110.
    A query at T1.5 sees 100; at T2.5 sees 110."""
    _, w, r, m = store
    release_ts_utc = datetime(2026, 4, 22, 11, 0, tzinfo=NY).astimezone(UTC)
    revision_ts_utc = release_ts_utc + timedelta(days=2)
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts_utc,
        data=_eia_vintage(100.0),
        provenance={"source": "eia.gov", "method": "test"},
    )
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts_utc,
        revision_ts=revision_ts_utc,
        data=_eia_vintage(110.0),
        provenance={"source": "eia.gov", "method": "test"},
    )
    # Build features at T1.5 (between release and revision).
    t1_5 = release_ts_utc + timedelta(hours=12)
    out_a = tmp_path / "rev_t1.parquet"
    df_a = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=release_ts_utc - timedelta(days=1),
        end=t1_5,
        output_path=out_a,
    )
    col = "eia__wpsr__WCESTUS1__value"
    post_mask_a = df_a.index > pd.Timestamp(release_ts_utc)
    assert (df_a.loc[post_mask_a, col] == 100.0).all()

    # And at T2.5 (after the revision).
    t2_5 = revision_ts_utc + timedelta(hours=12)
    out_b = tmp_path / "rev_t2.parquet"
    df_b = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=release_ts_utc - timedelta(days=1),
        end=t2_5,
        output_path=out_b,
    )
    post_mask_b = df_b.index > pd.Timestamp(revision_ts_utc)
    assert (df_b.loc[post_mask_b, col] == 110.0).all()


def test_output_parquet_round_trips(store, tmp_path):
    _, w, r, m = store
    release_ts_utc = datetime(2026, 4, 22, 11, 0, tzinfo=NY).astimezone(UTC)
    w.write_vintage(
        source="eia",
        dataset="wpsr",
        series="WCESTUS1",
        release_ts=release_ts_utc,
        data=_eia_vintage(440000.0),
        provenance={"source": "eia.gov", "method": "test"},
    )
    out = tmp_path / "subdir" / "features.parquet"
    df = build_features(
        manifest=m,
        reader=r,
        grid="daily",
        start=datetime(2026, 4, 20, 0, 0, tzinfo=UTC),
        end=datetime(2026, 4, 25, 0, 0, tzinfo=UTC),
        output_path=out,
    )
    assert out.exists()
    round_trip = pd.read_parquet(out)
    assert list(round_trip.columns) == list(df.columns)
    assert len(round_trip) == len(df)
