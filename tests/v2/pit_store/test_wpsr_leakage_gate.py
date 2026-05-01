"""Pinned WPSR pre/post-release leakage checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter

NY = ZoneInfo("America/New_York")


PINNED_WPSR_RELEASES = (
    datetime(2022, 4, 6, 10, 30, tzinfo=NY),
    datetime(2022, 7, 7, 10, 30, tzinfo=NY),
    datetime(2023, 4, 5, 10, 30, tzinfo=NY),
    datetime(2024, 1, 4, 10, 30, tzinfo=NY),
    datetime(2024, 6, 20, 10, 30, tzinfo=NY),
)


@pytest.mark.parametrize("release_local", PINNED_WPSR_RELEASES)
def test_wpsr_pre_release_sees_prior_week_post_release_sees_current(tmp_path, release_local):
    manifest = open_manifest(tmp_path)
    writer = PITWriter(tmp_path, manifest)
    reader = PITReader(tmp_path, manifest)
    try:
        release_ts = release_local.astimezone(UTC)
        usable_after = release_ts + timedelta(minutes=5)
        prior_release_ts = release_ts - timedelta(days=7)
        prior_usable_after = prior_release_ts + timedelta(minutes=5)

        writer.write_vintage(
            source="eia",
            dataset="wpsr",
            series="WCESTUS1",
            release_ts=prior_release_ts,
            usable_after_ts=prior_usable_after,
            data=pd.DataFrame({"value": [100.0]}),
            provenance={"source": "eia.gov", "method": "test_archive_csv"},
        )
        writer.write_vintage(
            source="eia",
            dataset="wpsr",
            series="WCESTUS1",
            release_ts=release_ts,
            usable_after_ts=usable_after,
            data=pd.DataFrame({"value": [200.0]}),
            provenance={"source": "eia.gov", "method": "test_archive_csv"},
        )

        pre = reader.as_of(
            "eia",
            "WCESTUS1",
            usable_after - timedelta(seconds=1),
            dataset="wpsr",
        )
        post = reader.as_of(
            "eia",
            "WCESTUS1",
            usable_after + timedelta(seconds=1),
            dataset="wpsr",
        )
        assert pre is not None
        assert post is not None
        assert pre.data["value"].iloc[0] == 100.0
        assert post.data["value"].iloc[0] == 200.0
    finally:
        manifest.close()
