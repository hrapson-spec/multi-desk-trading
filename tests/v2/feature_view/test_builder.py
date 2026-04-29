"""FeatureView builder tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from v2.feature_view import (
    FeatureAdmissibilityError,
    FeatureSpec,
    FeatureViewBuildError,
    build_data_quality_manifest,
    build_feature_view,
    render_data_quality_warning_block,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.quality import VintageQuality
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter


@pytest.fixture
def store(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    r = PITReader(tmp_path, m)
    try:
        yield tmp_path, w, m, r
    finally:
        m.close()


def _ingest(
    writer,
    source,
    series,
    release_ts,
    value,
    *,
    dataset=None,
    vintage_quality=VintageQuality.TRUE_FIRST_RELEASE.value,
):
    writer.write_vintage(
        source=source,
        dataset=dataset,
        series=series,
        release_ts=release_ts,
        data=pd.DataFrame({"value": [value]}),
        provenance={"source": source, "method": "test"},
        vintage_quality=vintage_quality,
    )


def test_build_populates_features_and_eligibility(store):
    _root, w, _m, reader = store
    release_ts = datetime(2026, 4, 15, 14, 30, tzinfo=UTC)
    _ingest(w, "eia_wpsr", "crude_stocks", release_ts, 425_000.0)
    _ingest(w, "wti_front_month", "spread_1_2", release_ts, -0.35)

    specs = [
        FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks"),
        FeatureSpec(name="spread", source="wti_front_month", series="spread_1_2"),
    ]
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    assert list(view.features.keys()) == ["crude", "spread"]
    assert view.missingness == {"crude": False, "spread": False}
    assert view.any_required_missing is False
    assert "eia_wpsr" in view.source_eligibility
    assert "wti_front_month" in view.source_eligibility
    assert view.worst_vintage_quality == VintageQuality.TRUE_FIRST_RELEASE.value
    assert view.data_quality_warning is False
    assert view.view_hash.startswith("") and len(view.view_hash) == 64


def test_missing_vintage_marks_feature_missing(store):
    _root, _w, _m, reader = store
    specs = [
        FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks"),
    ]
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    assert view.missingness["crude"] is True
    assert view.any_required_missing is True
    assert view.features["crude"] is None


def test_hash_is_deterministic_across_runs(store):
    _root, w, _m, reader = store
    _ingest(w, "eia_wpsr", "crude_stocks", datetime(2026, 4, 15, 14, 30, tzinfo=UTC), 425_000.0)
    specs = [FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks")]
    kw: dict = {
        "as_of_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        "family": "oil_wti_5d",
        "desk": "prompt_balance_nowcast",
        "specs": specs,
        "reader": reader,
    }
    v1 = build_feature_view(**kw)
    v2 = build_feature_view(**kw)
    assert v1.view_hash == v2.view_hash


def test_hash_differs_when_as_of_changes(store):
    _root, w, _m, reader = store
    _ingest(w, "eia_wpsr", "crude_stocks", datetime(2026, 4, 15, 14, 30, tzinfo=UTC), 425_000.0)
    _ingest(w, "eia_wpsr", "crude_stocks", datetime(2026, 4, 22, 14, 30, tzinfo=UTC), 427_500.0)

    specs = [FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks")]
    v_before = build_feature_view(
        as_of_ts=datetime(2026, 4, 20, 12, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    v_after = build_feature_view(
        as_of_ts=datetime(2026, 4, 23, 12, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    assert v_before.view_hash != v_after.view_hash


def test_naive_as_of_rejected(store):
    _root, _w, _m, reader = store
    with pytest.raises(FeatureViewBuildError):
        build_feature_view(
            as_of_ts=datetime(2026, 4, 22, 21, 0),
            family="oil_wti_5d",
            desk="prompt_balance_nowcast",
            specs=[],
            reader=reader,
        )


def test_unknown_transform_rejected(store):
    _root, w, _m, reader = store
    _ingest(w, "eia_wpsr", "crude_stocks", datetime(2026, 4, 15, 14, 30, tzinfo=UTC), 425_000.0)
    with pytest.raises(FeatureViewBuildError):
        build_feature_view(
            as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
            family="oil_wti_5d",
            desk="prompt_balance_nowcast",
            specs=[
                FeatureSpec(
                    name="crude",
                    source="eia_wpsr",
                    series="crude_stocks",
                    transform="nonexistent",
                ),
            ],
            reader=reader,
        )


def test_required_false_feature_missing_does_not_flag_any_required_missing(store):
    _root, _w, _m, reader = store
    specs = [
        FeatureSpec(
            name="crude",
            source="eia_wpsr",
            series="crude_stocks",
            required=False,
        ),
    ]
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    assert view.missingness["crude"] is True
    assert view.any_required_missing is False


def test_dataset_aware_feature_lookup(store):
    _root, w, _m, reader = store
    release_ts = datetime(2026, 4, 15, 14, 30, tzinfo=UTC)
    _ingest(w, "eia", "WCESTUS1", release_ts, 425_000.0, dataset="wpsr")
    specs = [FeatureSpec(name="crude", source="eia", dataset="wpsr", series="WCESTUS1")]
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    assert view.missingness["crude"] is False
    assert "eia/wpsr" in view.source_eligibility


def test_revision_quality_blocks_surprise(store):
    _root, w, _m, reader = store
    release_ts = datetime(2026, 4, 15, 14, 30, tzinfo=UTC)
    _ingest(
        w,
        "eia",
        "WCESTUS1",
        release_ts,
        425_000.0,
        dataset="wpsr",
        vintage_quality=VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
    )
    specs = [
        FeatureSpec(
            name="crude_surprise",
            source="eia",
            dataset="wpsr",
            series="WCESTUS1",
            feature_use="inventory_surprise_magnitude",
        )
    ]
    with pytest.raises(FeatureAdmissibilityError):
        build_feature_view(
            as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
            family="oil_wti_5d",
            desk="prompt_balance_nowcast",
            specs=specs,
            reader=reader,
        )


def test_latest_snapshot_not_pit_rejected_even_for_generic_feature(store):
    _root, w, _m, reader = store
    release_ts = datetime(2026, 4, 15, 14, 30, tzinfo=UTC)
    _ingest(
        w,
        "eia",
        "WCESTUS1",
        release_ts,
        425_000.0,
        dataset="wpsr",
        vintage_quality=VintageQuality.LATEST_SNAPSHOT_NOT_PIT.value,
    )
    specs = [FeatureSpec(name="crude", source="eia", dataset="wpsr", series="WCESTUS1")]
    with pytest.raises(FeatureAdmissibilityError):
        build_feature_view(
            as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
            family="oil_wti_5d",
            desk="prompt_balance_nowcast",
            specs=specs,
            reader=reader,
        )


def test_revision_quality_propagation(store):
    _root, w, _m, reader = store
    release_ts = datetime(2026, 4, 15, 14, 30, tzinfo=UTC)
    _ingest(
        w,
        "eia",
        "WCESTUS1",
        release_ts,
        425_000.0,
        dataset="wpsr",
        vintage_quality=VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
    )
    specs = [
        FeatureSpec(
            name="crude_sign_context",
            source="eia",
            dataset="wpsr",
            series="WCESTUS1",
            feature_use="return_sign_target",
        )
    ]
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        family="oil_wti_5d",
        desk="prompt_balance_nowcast",
        specs=specs,
        reader=reader,
    )
    assert view.vintage_quality["crude_sign_context"] == (
        VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value
    )
    assert view.worst_vintage_quality == VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value
    assert view.data_quality_warning is True
    assert view.degraded_inputs == ("eia/wpsr/WCESTUS1",)
    manifest = build_data_quality_manifest(view)
    assert manifest.to_dict() == {
        "data_quality_warning": True,
        "worst_vintage_quality": VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value,
        "degraded_inputs": ["eia/wpsr/WCESTUS1"],
    }
    report = render_data_quality_warning_block(view)
    assert "Data quality warning" in report
    assert "eia/wpsr/WCESTUS1" in report
