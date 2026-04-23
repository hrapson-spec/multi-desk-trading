"""DecisionV2 contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from v2.contracts import (
    FIXED_QUANTILE_LEVELS,
    ActionType,
    DecisionUnit,
    DecisionV2,
    DegradationState,
)
from v2.contracts.decision_v2 import HardGateResult


def _valid(**overrides):
    base: dict = {
        "family": "oil_wti_5d",
        "decision_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        "target_variable": "WTI_FRONT_1W_LOG_RETURN",
        "target_horizon": "5d",
        "decision_unit": DecisionUnit.LOG_RETURN,
        "instrument_spec": "WTI front-month under rolling_rule_v1",
        "roll_rule_id": "rolling_rule_v1",
        "action_type": ActionType.TARGET_RISK_BUDGET,
        "target_risk_budget": 0.35,
        "abstain": False,
        "abstain_reason": None,
        "degradation_state": DegradationState.HEALTHY,
        "valid_until_ts": datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
        "signal_strength": 0.62,
        "family_quantile_vector": (-0.08, -0.04, -0.01, 0.003, 0.015, 0.05, 0.09),
        "pred_scale": 0.035,
        "market_vol": 0.04,
        "regime_posterior": {"normal": 1.0},
        "hard_gates_passed": True,
        "contributing_forecast_ids": ["fct_abc"],
        "prereg_hash": "sha256:prereg",
        "contract_hash": "sha256:contract",
    }
    base.update(overrides)
    return base


def test_valid_decision():
    d = DecisionV2(**_valid())
    assert d.target_risk_budget == 0.35
    assert d.abstain is False


def test_abstain_requires_budget_none():
    with pytest.raises(ValidationError):
        DecisionV2(
            **_valid(
                abstain=True,
                abstain_reason="data hard gate",
                target_risk_budget=0.35,
                degradation_state=DegradationState.HARD_FAIL,
            )
        )


def test_abstain_true_with_budget_none_and_reason_ok():
    d = DecisionV2(
        **_valid(
            abstain=True,
            abstain_reason="required feature missing",
            target_risk_budget=None,
            degradation_state=DegradationState.SOFT_ABSTAIN,
        )
    )
    assert d.abstain is True
    assert d.target_risk_budget is None


def test_non_abstain_requires_budget():
    with pytest.raises(ValidationError):
        DecisionV2(**_valid(target_risk_budget=None))


def test_healthy_state_incompatible_with_abstain():
    with pytest.raises(ValidationError):
        DecisionV2(
            **_valid(
                abstain=True,
                abstain_reason="x",
                target_risk_budget=None,
                degradation_state=DegradationState.HEALTHY,
            )
        )


def test_non_abstain_requires_healthy_state():
    with pytest.raises(ValidationError):
        DecisionV2(**_valid(degradation_state=DegradationState.AGED))


def test_target_budget_bounds():
    with pytest.raises(ValidationError):
        DecisionV2(**_valid(target_risk_budget=1.5))
    with pytest.raises(ValidationError):
        DecisionV2(**_valid(target_risk_budget=-1.5))


def test_hard_gate_aggregate_must_agree():
    with pytest.raises(ValidationError):
        DecisionV2(
            **_valid(
                hard_gates_passed=True,
                hard_gate_results=[
                    HardGateResult(category="data", passed=False, reason="stock_out")
                ],
            )
        )


def test_family_quantile_levels_must_match_grid():
    with pytest.raises(ValidationError):
        DecisionV2(
            **_valid(
                family_quantile_levels=(0.05, 0.50, 0.95),
                family_quantile_vector=(-0.05, 0.0, 0.05),
            )
        )


def test_registry_enforced_on_decision():
    with pytest.raises(ValidationError):
        DecisionV2(**_valid(target_variable="NOT_IN_REGISTRY"))


def test_frozen_decision_is_immutable():
    d = DecisionV2(**_valid())
    with pytest.raises(ValidationError):
        d.target_risk_budget = 0.99  # type: ignore[misc]


def test_quantile_levels_default_is_fixed_grid():
    d = DecisionV2(**_valid())
    assert tuple(d.family_quantile_levels) == FIXED_QUANTILE_LEVELS
