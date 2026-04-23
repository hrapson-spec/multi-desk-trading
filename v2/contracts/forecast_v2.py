"""ForecastV2: the canonical desk output.

One ForecastV2 represents a desk's predictive distribution at a single
decision timestamp, published in the family's canonical decision unit.

Governed by docs/v2/v2_decision_contract.md §2. Contract version 2.0.1
(B3b) adds `emitted_ts`, `forecast_id`, `calibration_metadata`,
`feature_eligibility`, `contract_hash`, `release_calendar_version`,
`source_manifest_set_hash`, and `evidence_pack_ref`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from itertools import pairwise
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.target_variables import KNOWN_TARGETS

if TYPE_CHECKING:
    from v2.feature_view.view import FeatureView

CONTRACT_VERSION = "2.0.1"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class SourceEligibility(BaseModel):
    """Per-source eligibility snapshot attached to every forecast.

    Summarises what the desk saw at decision time for each data source
    it consumed at the SOURCE level. See FeatureEligibility for the
    per-feature (post-transform) counterpart.
    """

    model_config = ConfigDict(frozen=True)

    source: str
    eligible: bool
    release_lag_days: float = Field(ge=0.0)
    freshness_state: str  # fresh | stale_1w | stale_2w | stale_over_2w
    quality_multiplier: float = Field(ge=0.0, le=1.0)
    manifest_id: str | None = None


class FeatureEligibility(BaseModel):
    """Per-feature (post-transform) eligibility.

    Source-level eligibility is not enough: a feature can be present in
    the raw source but absent after transformation (e.g. when a rolling
    window's lookback is unavailable) or forward-filled from an older
    vintage. This sub-model captures that fidelity.
    """

    model_config = ConfigDict(frozen=True)

    feature_name: str
    source: str
    series: str | None = None
    transform: str = "identity"
    missing: bool = False
    freshness_state: str = "fresh"
    quality_multiplier: float = Field(default=1.0, ge=0.0, le=1.0)
    manifest_id: str | None = None
    forward_fill_used: bool = False


class CalibrationMetadata(BaseModel):
    """Makes `calibration_score` challengeable.

    The scalar `calibration_score` on ForecastV2 is not promotable on its
    own — Layer-3 review needs the method, baseline, and window behind
    the number. These fields are pre-registered in the desk's prereg
    and emitted on every ForecastV2.
    """

    model_config = ConfigDict(frozen=True)

    method: str  # e.g. "rolling_pinball_ratio"
    baseline_id: str  # e.g. "B0_ewma_gaussian"
    rolling_window_n: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    segment: str | None = None  # e.g. "post-EIA", "weekday"; None = unrestricted


# ---------------------------------------------------------------------------
# Main model
# ---------------------------------------------------------------------------


class ForecastV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    # -- identity -------------------------------------------------------------
    contract_version: str = CONTRACT_VERSION
    forecast_id: str  # content-addressed; validator checks match
    family_id: str
    desk_id: str
    distribution_version: str = ""

    # -- timestamps -----------------------------------------------------------
    decision_ts: datetime  # UTC-aware; economic "as-of" time
    emitted_ts: datetime  # UTC-aware; pipeline wall-clock at emit
    valid_until_ts: datetime  # UTC-aware; TTL

    # -- target ---------------------------------------------------------------
    target_variable: str
    target_horizon: str
    decision_unit: DecisionUnit

    # -- predictive distribution ---------------------------------------------
    quantile_levels: tuple[float, ...]
    quantile_vector: tuple[float, ...]

    # -- quality --------------------------------------------------------------
    calibration_score: float = Field(ge=0.0, le=1.0)
    calibration_metadata: CalibrationMetadata
    data_quality_score: float = Field(ge=0.0, le=1.0)

    # -- abstention -----------------------------------------------------------
    abstain: bool = False
    abstain_reason: str | None = None

    # -- provenance: feature + vintage --------------------------------------
    feature_view_hash: str
    source_eligibility: dict[str, SourceEligibility] = Field(default_factory=dict)
    feature_eligibility: dict[str, FeatureEligibility] = Field(default_factory=dict)
    source_manifest_set_hash: str

    # -- provenance: contract + code ----------------------------------------
    prereg_hash: str
    code_commit: str
    contract_hash: str
    release_calendar_version: str
    evidence_pack_ref: str | None = None

    # -------- validators ----------------------------------------------------

    @field_validator("decision_ts", "emitted_ts", "valid_until_ts")
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
            raise ValueError(
                f"target_horizon {self.target_horizon!r} disagrees with registry "
                f"for {self.target_variable}: expected {spec.horizon!r}"
            )

        # Quantile grid.
        if tuple(self.quantile_levels) != FIXED_QUANTILE_LEVELS:
            raise ValueError(
                f"quantile_levels must equal {FIXED_QUANTILE_LEVELS}; got {self.quantile_levels}"
            )
        if len(self.quantile_vector) != len(self.quantile_levels):
            raise ValueError("quantile_vector and quantile_levels must have equal length")

        # Monotonicity required when not abstaining.
        if not self.abstain and not all(a <= b for a, b in pairwise(self.quantile_vector)):
            raise ValueError("quantile_vector must be monotone non-decreasing")

        # Abstain semantics.
        if self.abstain and not self.abstain_reason:
            raise ValueError("abstain=True requires a non-empty abstain_reason")
        if (not self.abstain) and self.abstain_reason:
            raise ValueError("abstain_reason must be None when abstain=False")

        # Timestamp ordering.
        if self.valid_until_ts <= self.decision_ts:
            raise ValueError("valid_until_ts must be strictly after decision_ts")
        if self.emitted_ts < self.decision_ts:
            raise ValueError("emitted_ts must be at or after decision_ts")

        # Contract version.
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError(
                f"contract_version {self.contract_version!r} disagrees with "
                f"runtime {CONTRACT_VERSION!r}"
            )

        # forecast_id shape + content-address integrity.
        if not self.forecast_id.startswith("fct_"):
            raise ValueError(f"forecast_id must start with 'fct_'; got {self.forecast_id!r}")
        expected_id = _compute_forecast_id(self)
        if expected_id != self.forecast_id:
            raise ValueError(
                f"forecast_id mismatch: declared {self.forecast_id!r} but content "
                f"hashes to {expected_id!r}"
            )

        return self

    # -------- construction helper ------------------------------------------

    @classmethod
    def build_from_view(
        cls,
        *,
        view: FeatureView,
        family_id: str,
        desk_id: str,
        distribution_version: str,
        target_variable: str,
        target_horizon: str,
        decision_unit: DecisionUnit,
        quantile_vector: tuple[float, ...],
        calibration_score: float,
        calibration_metadata: CalibrationMetadata,
        data_quality_score: float,
        valid_until_ts: datetime,
        emitted_ts: datetime,
        prereg_hash: str,
        code_commit: str,
        contract_hash: str,
        release_calendar_version: str,
        abstain: bool = False,
        abstain_reason: str | None = None,
        evidence_pack_ref: str | None = None,
    ) -> ForecastV2:
        """Populate a ForecastV2 from a FeatureView + desk-computed inputs.

        This is the sanctioned construction path. The classmethod:
          1. Verifies `decision_ts == view.as_of_ts`.
          2. Derives per-feature `feature_eligibility` from view.
          3. Computes `source_manifest_set_hash`.
          4. Computes content-addressed `forecast_id`.
        """
        # decision_ts IS view.as_of_ts by contract.
        decision_ts = view.as_of_ts

        # Per-feature eligibility, derived from the view's specs + per-feature
        # observations. Source-level quality_multiplier is applied uniformly
        # to every feature sharing the source; the desk can tighten later.
        feature_eligibility: dict[str, FeatureEligibility] = {}
        for spec in view.specs:
            src_elig = view.source_eligibility.get(spec.source)
            feature_eligibility[spec.name] = FeatureEligibility(
                feature_name=spec.name,
                source=spec.source,
                series=spec.series,
                transform=spec.transform,
                missing=view.missingness.get(spec.name, False),
                freshness_state=view.stale_flags.get(spec.name, "unknown"),
                quality_multiplier=(src_elig.quality_multiplier if src_elig is not None else 0.0),
                manifest_id=view.manifest_ids.get(spec.name),
                forward_fill_used=view.forward_fill_used.get(spec.name, False),
            )

        # source_manifest_set_hash = SHA-256 over sorted non-null manifest_ids.
        manifest_ids = sorted(mid for mid in view.manifest_ids.values() if mid is not None)
        source_manifest_set_hash = hashlib.sha256(
            "|".join(manifest_ids).encode("utf-8")
        ).hexdigest()

        # forecast_id computed from the canonical hashable payload.
        payload_for_id = _canonical_id_payload(
            contract_version=CONTRACT_VERSION,
            family_id=family_id,
            desk_id=desk_id,
            distribution_version=distribution_version,
            decision_ts=decision_ts,
            emitted_ts=emitted_ts,
            valid_until_ts=valid_until_ts,
            target_variable=target_variable,
            target_horizon=target_horizon,
            decision_unit=decision_unit.value,
            quantile_levels=FIXED_QUANTILE_LEVELS,
            quantile_vector=quantile_vector,
            calibration_score=calibration_score,
            calibration_metadata=calibration_metadata.model_dump(),
            data_quality_score=data_quality_score,
            abstain=abstain,
            abstain_reason=abstain_reason,
            feature_view_hash=view.view_hash,
            source_eligibility={k: v.model_dump() for k, v in view.source_eligibility.items()},
            feature_eligibility={k: v.model_dump() for k, v in feature_eligibility.items()},
            source_manifest_set_hash=source_manifest_set_hash,
            prereg_hash=prereg_hash,
            code_commit=code_commit,
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
            evidence_pack_ref=evidence_pack_ref,
        )
        digest = hashlib.sha256(
            json.dumps(payload_for_id, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        forecast_id = f"fct_{digest[:16]}"

        return cls(
            forecast_id=forecast_id,
            family_id=family_id,
            desk_id=desk_id,
            distribution_version=distribution_version,
            decision_ts=decision_ts,
            emitted_ts=emitted_ts,
            valid_until_ts=valid_until_ts,
            target_variable=target_variable,
            target_horizon=target_horizon,
            decision_unit=decision_unit,
            quantile_levels=FIXED_QUANTILE_LEVELS,
            quantile_vector=quantile_vector,
            calibration_score=calibration_score,
            calibration_metadata=calibration_metadata,
            data_quality_score=data_quality_score,
            abstain=abstain,
            abstain_reason=abstain_reason,
            feature_view_hash=view.view_hash,
            source_eligibility=dict(view.source_eligibility),
            feature_eligibility=feature_eligibility,
            source_manifest_set_hash=source_manifest_set_hash,
            prereg_hash=prereg_hash,
            code_commit=code_commit,
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
            evidence_pack_ref=evidence_pack_ref,
        )


# ---------------------------------------------------------------------------
# Content-addressing helpers
# ---------------------------------------------------------------------------


def _canonical_id_payload(**fields: object) -> dict:
    """Order-insensitive canonical payload used for forecast_id hashing.

    All non-hashable objects are passed through json.dumps with
    sort_keys=True later; here we just ensure we accept dict/tuple/etc.
    """
    return dict(fields)


def _compute_forecast_id(forecast: ForecastV2) -> str:
    """Recompute forecast_id from a fully-constructed ForecastV2.

    Used by the post-construction validator to detect tampering.
    """
    payload = _canonical_id_payload(
        contract_version=forecast.contract_version,
        family_id=forecast.family_id,
        desk_id=forecast.desk_id,
        distribution_version=forecast.distribution_version,
        decision_ts=forecast.decision_ts,
        emitted_ts=forecast.emitted_ts,
        valid_until_ts=forecast.valid_until_ts,
        target_variable=forecast.target_variable,
        target_horizon=forecast.target_horizon,
        decision_unit=forecast.decision_unit.value,
        quantile_levels=tuple(forecast.quantile_levels),
        quantile_vector=tuple(forecast.quantile_vector),
        calibration_score=forecast.calibration_score,
        calibration_metadata=forecast.calibration_metadata.model_dump(),
        data_quality_score=forecast.data_quality_score,
        abstain=forecast.abstain,
        abstain_reason=forecast.abstain_reason,
        feature_view_hash=forecast.feature_view_hash,
        source_eligibility={k: v.model_dump() for k, v in forecast.source_eligibility.items()},
        feature_eligibility={k: v.model_dump() for k, v in forecast.feature_eligibility.items()},
        source_manifest_set_hash=forecast.source_manifest_set_hash,
        prereg_hash=forecast.prereg_hash,
        code_commit=forecast.code_commit,
        contract_hash=forecast.contract_hash,
        release_calendar_version=forecast.release_calendar_version,
        evidence_pack_ref=forecast.evidence_pack_ref,
    )
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    return f"fct_{digest[:16]}"
