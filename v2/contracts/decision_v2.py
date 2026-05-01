"""DecisionV2: family-level action record.

One DecisionV2 is emitted by the family synthesiser at each eligible
decision timestamp. It encodes the target risk budget under oil v2.0,
the full predictive quantile vector at family level, and every
provenance field needed for replay + audit.

Governed by docs/v2/v2_decision_contract.md §3 + §6.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.forecast_v2 import CONTRACT_VERSION
from v2.contracts.target_variables import KNOWN_TARGETS


class ActionType(StrEnum):
    TARGET_RISK_BUDGET = "target_risk_budget"


class DegradationState(StrEnum):
    HEALTHY = "healthy"
    SOFT_ABSTAIN = "soft_abstain"
    AGED = "aged"
    HARD_FAIL = "hard_fail"


class HardGateResult(BaseModel):
    """Result from evaluating one hard-gate category.

    Categories are enumerated in v2_decision_contract §4.2:
    data / model / operational.
    """

    model_config = ConfigDict(frozen=True)

    category: str  # "data" | "model" | "operational"
    passed: bool
    reason: str | None = None


class DecisionV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    # -- identity -------------------------------------------------------------
    contract_version: str = CONTRACT_VERSION
    family: str
    decision_ts: datetime

    # -- target + instrument -------------------------------------------------
    target_variable: str
    target_horizon: str
    decision_unit: DecisionUnit
    instrument_spec: str
    roll_rule_id: str  # e.g. "rolling_rule_v1"

    # -- action ---------------------------------------------------------------
    action_type: ActionType = ActionType.TARGET_RISK_BUDGET
    target_risk_budget: float | None = Field(default=None, ge=-1.0, le=1.0)
    abstain: bool = False
    abstain_reason: str | None = None
    degradation_state: DegradationState = DegradationState.HEALTHY

    # -- validity -------------------------------------------------------------
    valid_until_ts: datetime

    # -- signal diagnostics --------------------------------------------------
    signal_strength: float | None = None
    family_quantile_levels: tuple[float, ...] = FIXED_QUANTILE_LEVELS
    family_quantile_vector: tuple[float, ...] | None = None
    pred_scale: float | None = Field(default=None, ge=0.0)
    market_vol: float | None = Field(default=None, ge=0.0)  # ex-ante family-horizon vol

    # -- synthesiser multipliers ---------------------------------------------
    calibration_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    data_quality_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    roll_liquidity_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)

    # -- regime posterior (dict of regime_label → posterior) -----------------
    regime_posterior: dict[str, float] = Field(default_factory=dict)

    # -- gates + provenance --------------------------------------------------
    hard_gates_passed: bool = True
    hard_gate_results: list[HardGateResult] = Field(default_factory=list)
    contributing_forecast_ids: list[str] = Field(default_factory=list)
    prereg_hash: str
    contract_hash: str  # SHA-256 of docs/v2/v2_decision_contract.md at build time

    # -------- validators ----------------------------------------------------

    @field_validator("decision_ts", "valid_until_ts")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def _check_contract_invariants(self) -> Self:
        # Target variable + unit + horizon must match the registry.
        if self.target_variable not in KNOWN_TARGETS:
            raise ValueError(f"target_variable {self.target_variable!r} is not in the v2 registry")
        spec = KNOWN_TARGETS[self.target_variable]
        if self.decision_unit != spec.decision_unit:
            raise ValueError(
                f"decision_unit {self.decision_unit} disagrees with registry "
                f"for {self.target_variable}: expected {spec.decision_unit}"
            )
        if self.target_horizon != spec.horizon:
            raise ValueError(f"target_horizon {self.target_horizon!r} disagrees with registry")

        # Abstain invariant: target_risk_budget must be None iff abstain.
        if self.abstain and self.target_risk_budget is not None:
            raise ValueError(
                "abstain=True requires target_risk_budget=None "
                "(ABSTAIN is not an economic action; use b_t=0 for flat)"
            )
        if (not self.abstain) and self.target_risk_budget is None:
            raise ValueError("target_risk_budget is required when abstain=False")
        if self.abstain and not self.abstain_reason:
            raise ValueError("abstain=True requires a non-empty abstain_reason")
        if (not self.abstain) and self.abstain_reason:
            raise ValueError("abstain_reason must be None when abstain=False")

        # Degradation-ladder / abstain consistency.
        if self.abstain and self.degradation_state == DegradationState.HEALTHY:
            raise ValueError("abstain=True is incompatible with degradation_state=HEALTHY")
        if (not self.abstain) and self.degradation_state != DegradationState.HEALTHY:
            raise ValueError(
                "non-abstain decisions require degradation_state=HEALTHY; "
                "abstain/decay/hard_fail are operator states"
            )

        # Quantile grid.
        if self.family_quantile_vector is not None:
            if tuple(self.family_quantile_levels) != FIXED_QUANTILE_LEVELS:
                raise ValueError("family_quantile_levels must equal the fixed v2 grid")
            if len(self.family_quantile_vector) != len(self.family_quantile_levels):
                raise ValueError("family_quantile_vector and _levels must have equal length")
            if not self.abstain and not all(
                a <= b for a, b in pairwise(self.family_quantile_vector)
            ):
                raise ValueError("family_quantile_vector must be monotone")

        # hard_gates_passed must agree with hard_gate_results if provided.
        if self.hard_gate_results:
            all_passed = all(r.passed for r in self.hard_gate_results)
            if all_passed != self.hard_gates_passed:
                raise ValueError(
                    f"hard_gates_passed={self.hard_gates_passed} disagrees with "
                    f"per-gate results ({[r.passed for r in self.hard_gate_results]})"
                )

        # TTL.
        if self.valid_until_ts <= self.decision_ts:
            raise ValueError("valid_until_ts must be strictly after decision_ts")

        # Contract version must match the runtime constant.
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(
                f"contract_version {self.contract_version!r} disagrees with "
                f"runtime {CONTRACT_VERSION!r}"
            )

        return self
