"""RealisedOutcome: pairs a forecast's target with its realised Y_t.

A Layer-3 scoring pack needs the realised value of the target_variable
to compare against the forecast's predictive distribution. This model
is the PIT-safe pairing object: it records the forecast's decision_ts,
the timestamp at which Y was realised, and the realisation source so
audit can reconstruct it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class RealisedOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_variable: str
    decision_ts: datetime  # UTC-aware; matches ForecastV2.decision_ts
    realisation_ts: datetime  # UTC-aware; when Y_t was fully observable
    horizon_days: int
    realised_value: float
    source: str  # e.g. "wti_front_month"
    manifest_id: str | None = None  # vintage the realisation was read from

    @field_validator("decision_ts", "realisation_ts")
    @classmethod
    def _require_utc(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return v

    @model_validator(mode="after")
    def _check_ordering(self) -> Self:
        if self.realisation_ts < self.decision_ts:
            raise ValueError("realisation_ts must be >= decision_ts")
        if self.horizon_days <= 0:
            raise ValueError("horizon_days must be > 0")
        return self
