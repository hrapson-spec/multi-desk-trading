"""Core Pydantic v2 types for the multi-desk trading architecture (v1 API).

This module is the contract surface between desks and the rest of the system.
Frozen under the v1 major version. Breaking changes require a v2 module.

Semantic conventions (spec §4.2):
- Units live in field names (e.g. price_usd_bbl, not price).
- Timestamps are always timezone-aware UTC; naive datetimes are rejected.
- Horizons are a tagged union (ClockHorizon | EventHorizon).
- target_variable is constrained to contracts.target_variables.KNOWN_TARGETS.
- Directional claims are pre-registered and echoed in every Forecast.

See docs/architecture_spec_v1.md §4 for the authoritative definitions.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .target_variables import KNOWN_TARGETS

_FROZEN = ConfigDict(frozen=True)


class Provenance(BaseModel):
    """Identifies who/what produced this object and how to reconstruct it.

    code_commit MUST be the git SHA of the desk code at emission time.
    Development-mode emissions with uncommitted working-tree changes MAY
    use "<base_sha>-dirty" (flagged in audit log). Production-mode and
    replay-mode bus validators reject any Forecast whose code_commit ends
    with "-dirty" (spec §3.1, §4.3).
    """

    model_config = _FROZEN

    desk_name: str
    model_name: str
    model_version: str  # SemVer: MAJOR.MINOR.PATCH
    input_snapshot_hash: str  # hex digest of the ordered input-tuple
    spec_hash: str  # hex digest of the desk spec at emission time
    code_commit: str  # git SHA; "<sha>-dirty" allowed only in dev mode


class ClockHorizon(BaseModel):
    """Arbitrary-window research/backtest horizon.

    Use EventHorizon for any forecast pinned to a scheduled release (§4.7).
    """

    model_config = _FROZEN

    kind: Literal["clock"] = "clock"
    duration: timedelta


class EventHorizon(BaseModel):
    """Release-pinned horizon (EIA WPSR, CFTC COT, FOMC, NFP, etc.).

    expected_ts_utc never mutates post-emission (Forecast is immutable,
    spec §3.1). On event slip the Grade fires on actual Print arrival;
    the delta is recorded in Grade.schedule_slip_seconds (§4.7).
    """

    model_config = _FROZEN

    kind: Literal["event"] = "event"
    event_id: str
    expected_ts_utc: datetime

    @field_validator("expected_ts_utc")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("expected_ts_utc must be timezone-aware")
        return v


Horizon = ClockHorizon | EventHorizon


class UncertaintyInterval(BaseModel):
    model_config = _FROZEN

    level: float = Field(ge=0.0, lt=1.0)  # e.g. 0.80 for 80% band
    lower: float
    upper: float

    @model_validator(mode="after")
    def _ordered(self) -> UncertaintyInterval:
        if self.lower > self.upper:
            raise ValueError("lower must be ≤ upper")
        return self


class DirectionalClaim(BaseModel):
    """Pre-registered claim about which way the desk's signal should point.

    Required. A desk that cannot articulate a directional claim is not
    producing a testable signal and cannot emit Forecasts. sign="none"
    is permitted only for stubs.
    """

    model_config = _FROZEN

    variable: str
    sign: Literal["positive", "negative", "none"]


class Forecast(BaseModel):
    """Immutable emission from a desk at a point in time."""

    model_config = _FROZEN

    forecast_id: str
    emission_ts_utc: datetime
    target_variable: str
    horizon: Horizon
    point_estimate: float
    uncertainty: UncertaintyInterval
    directional_claim: DirectionalClaim
    staleness: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: Provenance
    supersedes: str | None = None

    @field_validator("emission_ts_utc")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("emission_ts_utc must be timezone-aware")
        return v

    @field_validator("target_variable")
    @classmethod
    def _in_registry(cls, v: str) -> str:
        if v not in KNOWN_TARGETS:
            raise ValueError(
                f"target_variable {v!r} is not in contracts.target_variables.KNOWN_TARGETS"
            )
        return v


class Print(BaseModel):
    """A realised outcome that grades one or more Forecasts."""

    model_config = _FROZEN

    print_id: str
    realised_ts_utc: datetime
    target_variable: str
    value: float
    event_id: str | None = None
    vintage_of: str | None = None

    @field_validator("realised_ts_utc")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("realised_ts_utc must be timezone-aware")
        return v

    @field_validator("target_variable")
    @classmethod
    def _in_registry(cls, v: str) -> str:
        if v not in KNOWN_TARGETS:
            raise ValueError(
                f"target_variable {v!r} is not in contracts.target_variables.KNOWN_TARGETS"
            )
        return v


class Grade(BaseModel):
    """Output of grading a Forecast against its matching Print."""

    model_config = _FROZEN

    grade_id: str
    forecast_id: str
    print_id: str
    grading_ts_utc: datetime
    squared_error: float
    absolute_error: float
    log_score: float | None = None
    sign_agreement: bool | None = None
    within_uncertainty: bool | None = None
    schedule_slip_seconds: float | None = None


class SignalWeight(BaseModel):
    """A row of the regime-conditional weight matrix.

    Controller state is a collection of these, indexed by (regime_id,
    desk_name, target_variable). The tuple is a non-unique index; reads
    break ties on same promotion_ts_utc by lexicographic weight_id
    (spec §8.3).
    """

    model_config = _FROZEN

    weight_id: str
    regime_id: str
    desk_name: str
    target_variable: str
    weight: float
    promotion_ts_utc: datetime
    validation_artefact: str  # path or "cold_start" or "rollback:<reason>"


class ControllerParams(BaseModel):
    """Per-regime scalar parameters for the linear sizing function (§8.2a).

    Separated from SignalWeight to preserve §4.6 registry invariant.
    """

    model_config = _FROZEN

    params_id: str
    regime_id: str
    k_regime: float
    pos_limit_regime: float
    promotion_ts_utc: datetime
    validation_artefact: str

    @field_validator("pos_limit_regime")
    @classmethod
    def _non_negative(cls, v: float) -> float:
        if v < 0.0:
            raise ValueError("pos_limit_regime must be ≥ 0")
        return v


class RegimeLabel(BaseModel):
    """Opaque regime label emitted by the regime classifier.

    Deliberately opaque: no contango/backwardation, no bull/bear.
    Controller reads regime_id (argmax) by default; regime_probabilities
    available for pre-registered weighted-average Controllers in future
    revisions (spec §10.2).
    """

    model_config = _FROZEN

    classification_ts_utc: datetime
    regime_id: str
    regime_probabilities: dict[str, float]
    transition_probabilities: dict[str, float]
    classifier_provenance: Provenance


class ResearchLoopEvent(BaseModel):
    """A trigger firing or a periodic review record (spec §6.2)."""

    model_config = _FROZEN

    event_id: str
    event_type: Literal[
        "gate_failure",
        "regime_transition",
        "weight_staleness",
        "attribution_anomaly",
        "correlation_shift",
        "desk_staleness",
        "controller_commission",
        "data_ingestion_failure",
        "periodic_weekly",
    ]
    triggered_at_utc: datetime
    priority: int = Field(ge=0, le=9)
    payload: dict[str, Any]
    completed_at_utc: datetime | None = None
    produced_artefact: str | None = None


class Decision(BaseModel):
    """Immutable Controller decision event (spec §3.1, §3.2 decisions table)."""

    model_config = _FROZEN

    decision_id: str
    emission_ts_utc: datetime
    regime_id: str
    combined_signal: float
    position_size: float
    input_forecast_ids: list[str]
    provenance: Provenance


class AttributionLodo(BaseModel):
    """Per-(decision, desk) LODO contribution (spec §9.1).

    Populated by attribution.lodo.compute_lodo; one row per desk that was
    part of the decision's regime weight row. contribution_metric units
    are defined by metric_name (e.g. "position_size_delta",
    "squared_error_delta"). The (decision_id, desk_name) pair is the
    indexed-but-non-unique lookup key (spec §3.2 grain fix).
    """

    model_config = _FROZEN

    attribution_id: str
    decision_id: str
    desk_name: str
    contribution_metric: float
    metric_name: str
    computed_ts_utc: datetime


class AttributionShapley(BaseModel):
    """Per-(review window, desk) Shapley credit score (spec §9.2)."""

    model_config = _FROZEN

    attribution_id: str
    review_ts_utc: datetime
    desk_name: str
    shapley_value: float
    metric_name: str
    n_decisions: int
    coalitions_mode: Literal["exact", "sampled"]


__all__ = [
    "AttributionLodo",
    "AttributionShapley",
    "Provenance",
    "ClockHorizon",
    "EventHorizon",
    "Horizon",
    "UncertaintyInterval",
    "DirectionalClaim",
    "Forecast",
    "Print",
    "Grade",
    "SignalWeight",
    "ControllerParams",
    "RegimeLabel",
    "ResearchLoopEvent",
    "Decision",
]
