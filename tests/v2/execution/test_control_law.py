"""Control-law tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from v2.contracts.decision_unit import DecisionUnit
from v2.execution import ControlLawParams, compute_target_risk_budget
from v2.synthesiser.linear_pool import DeskContribution, FamilyForecast


def _family(
    *,
    quantile_vector: tuple[float, ...] | None = (-0.08, -0.04, -0.01, 0.003, 0.015, 0.05, 0.09),
    abstain: bool = False,
    contributions: tuple[DeskContribution, ...] = (
        DeskContribution(
            desk_id="d1",
            forecast_id="fct_1",
            weight_raw=0.9,
            weight_normalised=1.0,
            calibration_score=0.7,
            data_quality_score=0.9,
            regime_weight=1.0,
        ),
    ),
) -> FamilyForecast:
    return FamilyForecast(
        family_id="oil_wti_5d",
        decision_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        target_variable="WTI_FRONT_1W_LOG_RETURN",
        target_horizon="5d",
        decision_unit=DecisionUnit.LOG_RETURN,
        quantile_vector=None if abstain else quantile_vector,
        abstain=abstain,
        abstain_reason="test" if abstain else None,
        contributing=list(contributions) if not abstain else [],
        abstaining_desk_ids=["d_x"] if abstain else [],
        regime_posterior={"normal": 1.0},
        contract_hash="sha256:c",
        release_calendar_version="eia_wpsr:1.0.0",
    )


def test_abstain_returns_none():
    assert compute_target_risk_budget(_family(abstain=True), params=ControlLawParams()) is None


def test_positive_median_positive_budget():
    # q50 = 0.003, σ_pred = (0.05 - (-0.04)) / z_90 ≈ 0.0274.
    # s = 0.003 / 0.0274 ≈ 0.110. With k=1, cal=0.7, dq=0.9:
    # b = 1 * 0.110 * 0.7 * 0.9 * 1.0 ≈ 0.069.
    b = compute_target_risk_budget(_family(), params=ControlLawParams(k=1.0))
    assert b is not None
    assert 0.0 < b < 0.2


def test_negative_median_negative_budget():
    qv = (-0.09, -0.05, -0.015, -0.003, 0.01, 0.04, 0.08)
    b = compute_target_risk_budget(_family(quantile_vector=qv), params=ControlLawParams(k=1.0))
    assert b is not None
    assert b < 0.0


def test_clipping_at_plus_one():
    # Large median with tiny spread → huge s → clipped to 1.0.
    qv = (0.01, 0.05, 0.08, 0.10, 0.12, 0.15, 0.19)
    b = compute_target_risk_budget(_family(quantile_vector=qv), params=ControlLawParams(k=10.0))
    assert b == 1.0


def test_sigma_floor_prevents_blowup():
    # Zero spread; σ_floor saves us.
    qv = (0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01)
    b = compute_target_risk_budget(
        _family(quantile_vector=qv),
        params=ControlLawParams(k=1.0, sigma_floor=0.01),
    )
    assert b is not None
    assert -1.0 <= b <= 1.0


def test_override_multipliers():
    b_full = compute_target_risk_budget(_family(), params=ControlLawParams(k=1.0))
    # Cut calibration to 0.1 via override → budget should shrink.
    b_muted = compute_target_risk_budget(
        _family(), params=ControlLawParams(k=1.0), calibration_multiplier=0.1
    )
    assert b_muted is not None and b_full is not None
    assert abs(b_muted) < abs(b_full)


def test_roll_multiplier_damps():
    b_full = compute_target_risk_budget(_family(), params=ControlLawParams(k=1.0))
    b_rolling = compute_target_risk_budget(
        _family(), params=ControlLawParams(k=1.0, roll_liquidity_multiplier=0.3)
    )
    assert b_rolling is not None and b_full is not None
    assert abs(b_rolling) < abs(b_full)


def test_invalid_sigma_floor_rejected():
    with pytest.raises(ValueError):
        ControlLawParams(sigma_floor=0.0)


def test_invalid_roll_multiplier_rejected():
    with pytest.raises(ValueError):
        ControlLawParams(roll_liquidity_multiplier=1.5)
