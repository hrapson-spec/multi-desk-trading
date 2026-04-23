"""compat.assert_compatible tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from v2.contracts import CalibrationMetadata, DecisionUnit, ForecastV2
from v2.feature_view import FeatureSpec, build_feature_view
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter
from v2.synthesiser import FamilyInputMismatchError, assert_compatible

_CAL = CalibrationMetadata(
    method="rolling_pinball_ratio",
    baseline_id="B0_ewma_gaussian",
    rolling_window_n=0,
    sample_count=0,
)


def _mint(tmp_path, **overrides) -> ForecastV2:
    m = open_manifest(tmp_path)
    try:
        w = PITWriter(tmp_path, m)
        w.write_vintage(
            source="eia_wpsr",
            series="crude_stocks",
            release_ts=datetime(2026, 4, 15, 14, 30, tzinfo=UTC),
            data=pd.DataFrame({"value": [1.0]}),
            provenance={"source": "eia_wpsr", "method": "test"},
        )
        reader = PITReader(tmp_path, m)
        view = build_feature_view(
            as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
            family="oil_wti_5d",
            desk="prompt_balance_nowcast",
            specs=[FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks")],
            reader=reader,
        )
        kwargs = {
            "family_id": "oil_wti_5d",
            "desk_id": "prompt_balance_nowcast",
            "distribution_version": "0.0.1-scaffold",
            "target_variable": "WTI_FRONT_1W_LOG_RETURN",
            "target_horizon": "5d",
            "decision_unit": DecisionUnit.LOG_RETURN,
            "quantile_vector": (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
            "calibration_score": 0.7,
            "calibration_metadata": _CAL,
            "data_quality_score": 0.9,
            "valid_until_ts": datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
            "emitted_ts": datetime(2026, 4, 22, 21, 5, tzinfo=UTC),
            "prereg_hash": "sha256:prereg",
            "code_commit": "abcdef0",
            "contract_hash": "sha256:contract",
            "release_calendar_version": "eia_wpsr:1.0.0",
        }
        kwargs.update(overrides)
        return ForecastV2.build_from_view(view=view, **kwargs)
    finally:
        m.close()


def test_empty_list_rejected():
    with pytest.raises(FamilyInputMismatchError):
        assert_compatible([])


def test_single_forecast_ok(tmp_path):
    assert_compatible([_mint(tmp_path)])


def test_family_id_mismatch_rejected(tmp_path):
    f1 = _mint(tmp_path / "a")
    f2 = _mint(tmp_path / "b", family_id="different_family")
    with pytest.raises(FamilyInputMismatchError, match="family_id mismatch"):
        assert_compatible([f1, f2])


def test_target_variable_mismatch_rejected(tmp_path):
    f1 = _mint(tmp_path / "a")
    # Keep family_id identical so the target_variable mismatch surfaces
    # rather than the family_id mismatch.
    f2 = _mint(
        tmp_path / "b",
        target_variable="VIX_30D_FORWARD_3D_DELTA",
        target_horizon="3d",
        decision_unit=DecisionUnit.VOL_POINT_CHANGE,
    )
    with pytest.raises(FamilyInputMismatchError):
        assert_compatible([f1, f2])


def test_decision_ts_mismatch_rejected(tmp_path):
    f1 = _mint(tmp_path / "a")
    # Force a different decision_ts by building a second view at a
    # different as_of_ts. decision_ts is derived from view.as_of_ts so
    # it cannot be overridden directly through _mint.
    m = open_manifest(tmp_path / "c")
    try:
        w = PITWriter(tmp_path / "c", m)
        w.write_vintage(
            source="eia_wpsr",
            series="crude_stocks",
            release_ts=datetime(2026, 4, 15, 14, 30, tzinfo=UTC),
            data=pd.DataFrame({"value": [1.0]}),
            provenance={"source": "eia_wpsr", "method": "test"},
        )
        reader = PITReader(tmp_path / "c", m)
        view2 = build_feature_view(
            as_of_ts=datetime(2026, 4, 29, 21, 0, tzinfo=UTC),  # different
            family="oil_wti_5d",
            desk="prompt_balance_nowcast",
            specs=[FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks")],
            reader=reader,
        )
        f3 = ForecastV2.build_from_view(
            view=view2,
            family_id="oil_wti_5d",
            desk_id="other_desk",
            distribution_version="0.0.1-scaffold",
            target_variable="WTI_FRONT_1W_LOG_RETURN",
            target_horizon="5d",
            decision_unit=DecisionUnit.LOG_RETURN,
            quantile_vector=(-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
            calibration_score=0.7,
            calibration_metadata=_CAL,
            data_quality_score=0.9,
            valid_until_ts=datetime(2026, 4, 30, 21, 0, tzinfo=UTC),
            emitted_ts=datetime(2026, 4, 29, 21, 5, tzinfo=UTC),
            prereg_hash="sha256:prereg",
            code_commit="abcdef0",
            contract_hash="sha256:contract",
            release_calendar_version="eia_wpsr:1.0.0",
        )
    finally:
        m.close()
    with pytest.raises(FamilyInputMismatchError, match="decision_ts"):
        assert_compatible([f1, f3])
