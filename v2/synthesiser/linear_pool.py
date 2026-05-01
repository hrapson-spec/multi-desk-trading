"""Synthesiser entry point + FamilyForecast output model.

Flow:
    1. `assert_compatible(forecasts)` — strict family invariants.
    2. Family-abstain cascade: if any input has `abstain=True`, family
       emits an abstaining FamilyForecast with cascade reason.
    3. Per-desk weighting: w_raw = calibration × data_quality × regime.
       A zero weight is desk-level exclusion (drop + renormalise).
    4. If all desks excluded, family abstains.
    5. Otherwise, CDF-space weighted linear pool on the surviving set.

At v2.0 `regime_posterior` is pass-through metadata: it is recorded on
the FamilyForecast, its values sum to 1.0 by v2.0 convention, and it
contributes 1.0 to weight. Per-desk regime-weighted pooling activates
at v2.2 alongside the real regime classifier.

The family-level provenance fields (`contract_hash`,
`release_calendar_version`) must match the shared values on the input
ForecastV2s. The synthesiser will not stamp caller-supplied provenance
onto a pooled forecast if it disagrees with the desks it combined.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.forecast_v2 import CONTRACT_VERSION, ForecastV2
from v2.synthesiser.compat import FamilyInputMismatchError, assert_compatible
from v2.synthesiser.pool import weighted_linear_pool_cdf


class DeskContribution(BaseModel):
    """Per-desk record of what the synthesiser did with that forecast."""

    model_config = ConfigDict(frozen=True)

    desk_id: str
    forecast_id: str
    weight_raw: float = Field(ge=0.0)  # pre-renormalisation
    weight_normalised: float = Field(ge=0.0, le=1.0)  # post-renormalisation
    calibration_score: float = Field(ge=0.0, le=1.0)
    data_quality_score: float = Field(ge=0.0, le=1.0)
    regime_weight: float = Field(ge=0.0, le=1.0)


class FamilyForecast(BaseModel):
    """Family-level predictive distribution (or abstention)."""

    model_config = ConfigDict(frozen=True)

    # -- identity -----------------------------------------------------------
    contract_version: str = CONTRACT_VERSION
    family_id: str
    decision_ts: datetime  # UTC-aware

    # -- target -------------------------------------------------------------
    target_variable: str
    target_horizon: str
    decision_unit: DecisionUnit

    # -- predictive distribution -------------------------------------------
    quantile_levels: tuple[float, ...] = FIXED_QUANTILE_LEVELS
    quantile_vector: tuple[float, ...] | None = None  # None iff abstain

    # -- abstention ---------------------------------------------------------
    abstain: bool = False
    abstain_reason: str | None = None

    # -- contributions ------------------------------------------------------
    contributing: list[DeskContribution] = Field(default_factory=list)
    excluded_desk_ids: list[str] = Field(default_factory=list)  # dropped, zero-weight
    abstaining_desk_ids: list[str] = Field(default_factory=list)  # cascaded abstain

    # -- regime pass-through ------------------------------------------------
    regime_posterior: dict[str, float] = Field(default_factory=dict)

    # -- provenance (inherited from contributing forecasts) ---------------
    contract_hash: str
    release_calendar_version: str

    @field_validator("decision_ts")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("decision_ts must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def _check_invariants(self) -> Self:
        if self.abstain:
            if not self.abstain_reason:
                raise ValueError("abstain=True requires non-empty abstain_reason")
            if self.quantile_vector is not None:
                raise ValueError("abstain=True requires quantile_vector=None")
            if self.contributing:
                raise ValueError(
                    "abstain=True requires no contributing desks "
                    "(contributions are recorded under abstaining_desk_ids instead)"
                )
        else:
            if self.abstain_reason is not None:
                raise ValueError("abstain_reason must be None when abstain=False")
            if self.quantile_vector is None:
                raise ValueError("non-abstaining family forecast requires quantile_vector")
            if len(self.quantile_vector) != len(self.quantile_levels):
                raise ValueError("quantile_vector length must match quantile_levels")
            if not self.contributing:
                raise ValueError("non-abstaining family forecast requires >= 1 contributing desk")
            total = sum(c.weight_normalised for c in self.contributing)
            if not (0.999 <= total <= 1.001):
                raise ValueError(f"contributing weight_normalised must sum to 1.0 (got {total})")

        if tuple(self.quantile_levels) != FIXED_QUANTILE_LEVELS:
            raise ValueError(f"quantile_levels must equal {FIXED_QUANTILE_LEVELS}")

        return self


def synthesise_family(
    forecasts: list[ForecastV2],
    *,
    regime_posterior: dict[str, float] | None = None,
    contract_hash: str,
    release_calendar_version: str,
) -> FamilyForecast:
    """Combine per-desk forecasts into a family-level FamilyForecast.

    See module docstring for the stage-by-stage flow.
    """
    assert_compatible(forecasts)
    ref = forecasts[0]
    if contract_hash != ref.contract_hash:
        raise FamilyInputMismatchError(
            "family contract_hash must match input forecasts: "
            f"{contract_hash!r} vs {ref.contract_hash!r}"
        )
    if release_calendar_version != ref.release_calendar_version:
        raise FamilyInputMismatchError(
            "family release_calendar_version must match input forecasts: "
            f"{release_calendar_version!r} vs {ref.release_calendar_version!r}"
        )

    rp = dict(regime_posterior) if regime_posterior else {"normal": 1.0}
    if not rp:
        raise ValueError("regime_posterior must not be empty")
    if any(value < 0.0 or value > 1.0 for value in rp.values()):
        raise ValueError("regime_posterior values must lie in [0.0, 1.0]")
    rp_sum = sum(rp.values())
    if not (0.999 <= rp_sum <= 1.001):
        raise ValueError(f"regime_posterior values must sum to 1.0 (got {rp_sum})")

    # Stage: family-abstain cascade.
    abstaining = [f for f in forecasts if f.abstain]
    if abstaining:
        ids = [f.desk_id for f in abstaining]
        return FamilyForecast(
            family_id=ref.family_id,
            decision_ts=ref.decision_ts,
            target_variable=ref.target_variable,
            target_horizon=ref.target_horizon,
            decision_unit=ref.decision_unit,
            quantile_vector=None,
            abstain=True,
            abstain_reason=f"cascade: {len(abstaining)} desk(s) abstaining: {ids}",
            contributing=[],
            excluded_desk_ids=[],
            abstaining_desk_ids=ids,
            regime_posterior=rp,
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
        )

    # Stage: weights + desk-level exclusion.
    # At v2.0 every non-abstaining desk sees regime_weight = sum(rp) = 1.0
    # (constant-posterior pass-through). Per-desk regime weighting lands
    # with the v2.2 regime classifier.
    regime_weight_per_desk = 1.0
    excluded_ids: list[str] = []
    raw_contribs: list[tuple[float, ForecastV2]] = []
    for f in forecasts:
        w_raw = (
            f.calibration_score
            * f.data_quality_score
            * regime_weight_per_desc_guard(regime_weight_per_desk)
        )
        if w_raw <= 0.0:
            excluded_ids.append(f.desk_id)
        else:
            raw_contribs.append((w_raw, f))

    if not raw_contribs:
        return FamilyForecast(
            family_id=ref.family_id,
            decision_ts=ref.decision_ts,
            target_variable=ref.target_variable,
            target_horizon=ref.target_horizon,
            decision_unit=ref.decision_unit,
            quantile_vector=None,
            abstain=True,
            abstain_reason=(
                f"all desks excluded (zero weight): {excluded_ids}"
                if excluded_ids
                else "no desks contributed"
            ),
            contributing=[],
            excluded_desk_ids=excluded_ids,
            abstaining_desk_ids=[],
            regime_posterior=rp,
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
        )

    # Stage: renormalise + pool.
    total_raw = sum(w for w, _ in raw_contribs)
    pool_inputs: list[tuple[float, tuple[float, ...]]] = [
        (w / total_raw, tuple(f.quantile_vector)) for w, f in raw_contribs
    ]
    family_qv = weighted_linear_pool_cdf(pool_inputs)

    contributions = [
        DeskContribution(
            desk_id=f.desk_id,
            forecast_id=f.forecast_id,
            weight_raw=w_raw,
            weight_normalised=w_raw / total_raw,
            calibration_score=f.calibration_score,
            data_quality_score=f.data_quality_score,
            regime_weight=regime_weight_per_desk,
        )
        for w_raw, f in raw_contribs
    ]

    return FamilyForecast(
        family_id=ref.family_id,
        decision_ts=ref.decision_ts,
        target_variable=ref.target_variable,
        target_horizon=ref.target_horizon,
        decision_unit=ref.decision_unit,
        quantile_vector=family_qv,
        abstain=False,
        abstain_reason=None,
        contributing=contributions,
        excluded_desk_ids=excluded_ids,
        abstaining_desk_ids=[],
        regime_posterior=rp,
        contract_hash=contract_hash,
        release_calendar_version=release_calendar_version,
    )


def regime_weight_per_desc_guard(w: float) -> float:
    """Tiny shim that exists so v2.2 can swap in the per-desk regime
    weighting without touching synthesise_family. At v2.0 it is
    identity; the indirection keeps the v2.2 diff small."""
    return w
