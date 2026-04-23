"""ForecastV2 contract tests (contract v2.0.1 / B3b).

B3b adds: emitted_ts, forecast_id (content-addressed), calibration_metadata,
feature_eligibility, contract_hash, release_calendar_version,
source_manifest_set_hash, evidence_pack_ref.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pandas as pd
import pytest
from pydantic import ValidationError

from v2.contracts import (
    FIXED_QUANTILE_LEVELS,
    CalibrationMetadata,
    DecisionUnit,
    FeatureEligibility,
    ForecastV2,
    SourceEligibility,
)
from v2.feature_view import FeatureSpec, build_feature_view
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter

_CAL = CalibrationMetadata(
    method="rolling_pinball_ratio",
    baseline_id="B0_ewma_gaussian",
    rolling_window_n=260,
    sample_count=780,
    segment="post-EIA",
)


def _valid_kwargs(forecast_id: str = "fct_0000000000000000", **overrides) -> dict:
    """Canonical kwargs. Note: forecast_id is a placeholder; use
    _mint_valid_forecast() to get an object whose id matches its payload."""
    base: dict = {
        "forecast_id": forecast_id,
        "family_id": "oil_wti_5d",
        "desk_id": "prompt_balance_nowcast",
        "distribution_version": "0.0.1-scaffold",
        "decision_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        "emitted_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        "valid_until_ts": datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
        "target_variable": "WTI_FRONT_1W_LOG_RETURN",
        "target_horizon": "5d",
        "decision_unit": DecisionUnit.LOG_RETURN,
        "quantile_levels": FIXED_QUANTILE_LEVELS,
        "quantile_vector": (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
        "calibration_score": 0.7,
        "calibration_metadata": _CAL,
        "data_quality_score": 0.9,
        "feature_view_hash": "sha256:view",
        "source_eligibility": {},
        "feature_eligibility": {},
        "source_manifest_set_hash": hashlib.sha256(b"").hexdigest(),
        "prereg_hash": "sha256:prereg",
        "code_commit": "abcdef0",
        "contract_hash": "sha256:contract",
        "release_calendar_version": "eia_wpsr:1.0.0",
    }
    base.update(overrides)
    return base


def _mint(forecast_kwargs_overrides: dict | None = None) -> ForecastV2:
    """Build a ForecastV2 whose forecast_id matches its payload by using
    build_from_view with a synthetic empty FeatureView."""
    # Build a tiny view in an in-memory tmp DuckDB.
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp())
    m = open_manifest(tmp)
    try:
        w = PITWriter(tmp, m)
        w.write_vintage(
            source="eia_wpsr",
            series="crude_stocks",
            release_ts=datetime(2026, 4, 15, 14, 30, tzinfo=UTC),
            data=pd.DataFrame({"value": [1.0]}),
            provenance={"source": "eia_wpsr", "method": "test"},
        )
        reader = PITReader(tmp, m)
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
        if forecast_kwargs_overrides:
            kwargs.update(forecast_kwargs_overrides)
        return ForecastV2.build_from_view(view=view, **kwargs)
    finally:
        m.close()


# --- direct-ctor contract invariant tests -----------------------------------


def test_direct_ctor_rejects_bad_forecast_id():
    # forecast_id does not match recomputed hash.
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(forecast_id="fct_deadbeefdeadbeef"))


def test_forecast_id_must_start_with_fct():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(forecast_id="xyz_123"))


def test_emitted_ts_must_follow_decision_ts():
    with pytest.raises(ValidationError):
        _mint(
            {
                "emitted_ts": datetime(2026, 4, 22, 20, 59, tzinfo=UTC),
            }
        )


def test_naive_emitted_ts_rejected():
    with pytest.raises(ValidationError):
        _mint({"emitted_ts": datetime(2026, 4, 22, 21, 5)})


def test_non_monotone_quantiles_rejected_when_not_abstain():
    with pytest.raises(ValidationError):
        _mint(
            {
                "quantile_vector": (-0.10, -0.05, 0.10, 0.0, 0.02, 0.05, 0.08),
            }
        )


def test_unregistered_target_rejected():
    with pytest.raises(ValidationError):
        _mint({"target_variable": "NOT_IN_REGISTRY"})


def test_unit_disagreement_rejected():
    with pytest.raises(ValidationError):
        _mint({"decision_unit": DecisionUnit.VOL_POINT_CHANGE})


def test_ttl_must_be_after_decision_ts():
    with pytest.raises(ValidationError):
        _mint(
            {
                "valid_until_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
            }
        )


def test_score_bounds():
    with pytest.raises(ValidationError):
        _mint({"calibration_score": 1.1})
    with pytest.raises(ValidationError):
        _mint({"data_quality_score": -0.1})


def test_frozen_forecast_is_immutable():
    f = _mint()
    with pytest.raises(ValidationError):
        f.calibration_score = 0.1  # type: ignore[misc]


# --- B3b: new-field behaviour -----------------------------------------------


def test_build_from_view_is_reproducible(tmp_path):
    # Use a SHARED tmp_path + manifest so manifest_ids are stable across
    # the two build_from_view calls.
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
        f1 = ForecastV2.build_from_view(view=view, **kwargs)
        f2 = ForecastV2.build_from_view(view=view, **kwargs)
        assert f1.forecast_id == f2.forecast_id
        assert f1.forecast_id.startswith("fct_")
        assert len(f1.forecast_id) == len("fct_") + 16
    finally:
        m.close()


def test_forecast_id_changes_when_emitted_ts_changes():
    f1 = _mint({"emitted_ts": datetime(2026, 4, 22, 21, 5, tzinfo=UTC)})
    f2 = _mint({"emitted_ts": datetime(2026, 4, 22, 21, 6, tzinfo=UTC)})
    assert f1.forecast_id != f2.forecast_id


def test_forecast_id_changes_when_quantile_vector_changes():
    f1 = _mint()
    f2 = _mint({"quantile_vector": (-0.12, -0.06, -0.02, 0.0, 0.02, 0.06, 0.12)})
    assert f1.forecast_id != f2.forecast_id


def test_tampered_payload_breaks_id_validator():
    """Reconstructing via direct ctor with a mismatched forecast_id is rejected."""
    f = _mint()
    # Copy its kwargs but change the quantile vector: id will no longer match.
    kwargs = f.model_dump()
    kwargs["quantile_vector"] = tuple(q + 0.01 for q in f.quantile_vector)
    with pytest.raises(ValidationError):
        ForecastV2.model_validate(kwargs)


def test_feature_eligibility_populated_from_view():
    f = _mint()
    assert "crude" in f.feature_eligibility
    fe = f.feature_eligibility["crude"]
    assert isinstance(fe, FeatureEligibility)
    assert fe.source == "eia_wpsr"
    assert fe.series == "crude_stocks"
    assert fe.missing is False
    assert fe.forward_fill_used is False


def test_source_manifest_set_hash_shape():
    # Single-call check that the hash is a hex SHA-256 (determinism across
    # calls is exercised in test_build_from_view_is_reproducible).
    f = _mint()
    assert len(f.source_manifest_set_hash) == 64
    int(f.source_manifest_set_hash, 16)


def test_source_manifest_set_hash_reflects_manifest_ids():
    f = _mint()
    expected = hashlib.sha256(
        "|".join(
            sorted(fe.manifest_id for fe in f.feature_eligibility.values() if fe.manifest_id)
        ).encode("utf-8")
    ).hexdigest()
    assert f.source_manifest_set_hash == expected


def test_calibration_metadata_is_mandatory():
    kwargs = _valid_kwargs()
    del kwargs["calibration_metadata"]
    with pytest.raises(ValidationError):
        ForecastV2(**kwargs)


def test_abstain_still_accepts_non_monotone_vector():
    f = _mint(
        {
            "quantile_vector": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            "abstain": True,
            "abstain_reason": "required feature missing",
        }
    )
    assert f.abstain is True


def test_decision_unit_must_match_registry_even_when_emitted_via_build():
    with pytest.raises(ValidationError):
        _mint({"decision_unit": DecisionUnit.VOL_POINT_CHANGE})


def test_contract_version_is_2_0_1():
    f = _mint()
    assert f.contract_version == "2.0.1"


def test_sample_eligibility_roundtrip_through_json():
    """forecast_id stays consistent after model_dump→validate round-trip."""
    f = _mint()
    data = f.model_dump()
    # Re-serialise via JSON too to ensure dump format is stable.
    data = json.loads(json.dumps(data, default=str))
    # Pydantic needs DecisionUnit as enum value on re-validation; it accepts strings.
    rebuilt = ForecastV2.model_validate(data)
    assert rebuilt.forecast_id == f.forecast_id


def test_source_eligibility_survives_build():
    f = _mint()
    assert "eia_wpsr" in f.source_eligibility
    assert isinstance(f.source_eligibility["eia_wpsr"], SourceEligibility)
