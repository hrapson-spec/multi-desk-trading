"""ForecastV2 contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from v2.contracts import FIXED_QUANTILE_LEVELS, DecisionUnit, ForecastV2


def _valid_kwargs(**overrides):
    base: dict = {
        "family_id": "oil_wti_5d",
        "desk_id": "prompt_balance_nowcast",
        "decision_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        "target_variable": "WTI_FRONT_1W_LOG_RETURN",
        "target_horizon": "5d",
        "decision_unit": DecisionUnit.LOG_RETURN,
        "quantile_levels": FIXED_QUANTILE_LEVELS,
        "quantile_vector": (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
        "calibration_score": 0.7,
        "data_quality_score": 0.9,
        "valid_until_ts": datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
        "feature_view_hash": "sha256:view",
        "prereg_hash": "sha256:prereg",
        "code_commit": "abcdef0",
    }
    base.update(overrides)
    return base


def test_valid_forecast_roundtrips():
    f = ForecastV2(**_valid_kwargs())
    assert f.abstain is False
    assert f.quantile_vector[3] == 0.0


def test_unregistered_target_rejected():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(target_variable="NOT_IN_REGISTRY"))


def test_unit_disagreement_rejected():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(decision_unit=DecisionUnit.VOL_POINT_CHANGE))


def test_horizon_disagreement_rejected():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(target_horizon="3d"))


def test_non_monotone_quantiles_rejected_when_not_abstain():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(quantile_vector=(-0.10, -0.05, 0.10, 0.0, 0.02, 0.05, 0.08)))


def test_non_monotone_quantiles_accepted_when_abstain():
    f = ForecastV2(
        **_valid_kwargs(
            quantile_vector=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            abstain=True,
            abstain_reason="required feature missing",
        )
    )
    assert f.abstain


def test_abstain_requires_reason():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(abstain=True))


def test_abstain_reason_forbidden_when_not_abstaining():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(abstain_reason="ghost"))


def test_naive_timestamp_rejected():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(decision_ts=datetime(2026, 4, 22, 21, 0)))


def test_ttl_must_be_after_decision_ts():
    ts = datetime(2026, 4, 22, 21, 0, tzinfo=UTC)
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(decision_ts=ts, valid_until_ts=ts))


def test_quantile_levels_must_match_fixed_grid():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(quantile_levels=(0.05, 0.50, 0.95)))


def test_score_bounds():
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(calibration_score=1.1))
    with pytest.raises(ValidationError):
        ForecastV2(**_valid_kwargs(data_quality_score=-0.1))


def test_frozen_forecast_is_immutable():
    f = ForecastV2(**_valid_kwargs())
    with pytest.raises(ValidationError):
        f.calibration_score = 0.1  # type: ignore[misc]
