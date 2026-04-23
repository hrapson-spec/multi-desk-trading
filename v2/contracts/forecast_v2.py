"""ForecastV2: the canonical desk output.

One ForecastV2 represents a desk's predictive distribution at a single
decision timestamp, published in the family's canonical decision unit.

Governed by docs/v2/v2_decision_contract.md §2.
"""

from __future__ import annotations

from datetime import datetime
from itertools import pairwise
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.target_variables import KNOWN_TARGETS

CONTRACT_VERSION = "2.0.0"


class SourceEligibility(BaseModel):
    """Per-source eligibility snapshot attached to every forecast.

    Summarises what the desk saw at decision time for each data source
    it consumed: was the row decision-eligible, how stale was it, what
    quality multiplier did the reader assign, and which manifest row
    was used.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    eligible: bool
    release_lag_days: float = Field(ge=0.0)
    freshness_state: str  # fresh | stale_1w | stale_2w | stale_over_2w
    quality_multiplier: float = Field(ge=0.0, le=1.0)
    manifest_id: str | None = None


class ForecastV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    # -- identity -------------------------------------------------------------
    contract_version: str = CONTRACT_VERSION
    family_id: str
    desk_id: str
    decision_ts: datetime  # UTC-aware
    distribution_version: str = ""

    # -- target ---------------------------------------------------------------
    target_variable: str
    target_horizon: str
    decision_unit: DecisionUnit

    # -- predictive distribution ---------------------------------------------
    quantile_levels: tuple[float, ...]
    quantile_vector: tuple[float, ...]

    # -- quality / validity ---------------------------------------------------
    calibration_score: float = Field(ge=0.0, le=1.0)
    data_quality_score: float = Field(ge=0.0, le=1.0)
    valid_until_ts: datetime  # UTC-aware

    # -- abstention -----------------------------------------------------------
    abstain: bool = False
    abstain_reason: str | None = None

    # -- provenance -----------------------------------------------------------
    feature_view_hash: str
    prereg_hash: str
    code_commit: str

    # -- source eligibility summary ------------------------------------------
    source_eligibility: dict[str, SourceEligibility] = Field(default_factory=dict)

    # -------- validators ----------------------------------------------------

    @field_validator("decision_ts", "valid_until_ts")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def _check_contract_invariants(self) -> Self:
        # Target variable must be registered.
        if self.target_variable not in KNOWN_TARGETS:
            raise ValueError(f"target_variable {self.target_variable!r} is not in the v2 registry")
        spec = KNOWN_TARGETS[self.target_variable]
        if self.decision_unit != spec.decision_unit:
            raise ValueError(
                f"decision_unit {self.decision_unit} disagrees with registry "
                f"for {self.target_variable}: expected {spec.decision_unit}"
            )
        if self.target_horizon != spec.horizon:
            raise ValueError(
                f"target_horizon {self.target_horizon!r} disagrees with registry "
                f"for {self.target_variable}: expected {spec.horizon!r}"
            )

        # Quantile grid must be the fixed grid.
        if tuple(self.quantile_levels) != FIXED_QUANTILE_LEVELS:
            raise ValueError(
                f"quantile_levels must equal {FIXED_QUANTILE_LEVELS}; got {self.quantile_levels}"
            )
        if len(self.quantile_vector) != len(self.quantile_levels):
            raise ValueError("quantile_vector and quantile_levels must have equal length")

        # Monotonicity is required when NOT abstaining. An abstained
        # forecast still carries the grid but the numeric values are
        # not required to represent a usable distribution.
        if not self.abstain and not all(a <= b for a, b in pairwise(self.quantile_vector)):
            raise ValueError("quantile_vector must be monotone non-decreasing")

        # Abstain semantics.
        if self.abstain and not self.abstain_reason:
            raise ValueError("abstain=True requires a non-empty abstain_reason")
        if (not self.abstain) and self.abstain_reason:
            raise ValueError("abstain_reason must be None when abstain=False")

        # TTL must be in the future relative to decision_ts.
        if self.valid_until_ts <= self.decision_ts:
            raise ValueError("valid_until_ts must be strictly after decision_ts")

        # Contract version must be the current build constant.
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(
                f"contract_version {self.contract_version!r} disagrees with "
                f"runtime {CONTRACT_VERSION!r}"
            )

        return self
