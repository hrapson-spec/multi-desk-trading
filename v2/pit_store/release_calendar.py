"""Release-calendar YAML loader.

Per-source calendars declare publisher timing, revision policy, source
confidence, and per-freshness quality multipliers. Calendar schema is
governed by docs/v2/v2_data_contract.md §4.

Risk-acceptance note: calendar correctness is validated in tests, NOT at
runtime (docs/v2/v2_data_contract.md §1.2). The loader validates structural
integrity; semantic correctness (does the declared release-time match the
publisher?) is the test suite's responsibility.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class ReleaseCadence(BaseModel):
    type: Literal["weekly", "biweekly", "monthly", "quarterly", "daily", "irregular"]
    weekday: Literal[
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "none"
    ] = "none"
    earliest_release_time_et: str = "00:00"  # HH:MM
    holiday_rule: Literal[
        "shift_next_business_day",
        "shift_prior_business_day",
        "skip",
        "none",
    ] = "none"


class ObservationSemantics(BaseModel):
    reporting_period: str
    lag_to_publication_days: float


class SourceConfidence(BaseModel):
    baseline: float = Field(ge=0.0, le=1.0)
    degradation_conditions: list[str] = Field(default_factory=list)


class DataQualityMultipliers(BaseModel):
    """Freshness-band → quality multiplier. A value of 0.0 is a hard gate."""

    fresh: float = Field(default=1.0, ge=0.0, le=1.0)
    stale_1week: float = Field(default=0.85, ge=0.0, le=1.0)
    stale_2week: float = Field(default=0.60, ge=0.0, le=1.0)
    stale_over_2week: float = Field(default=0.0, ge=0.0, le=1.0)


class ReleaseCalendar(BaseModel):
    source: str
    description: str = ""
    publisher: str = ""
    calendar_version: str = "1.0.0"
    release_cadence: ReleaseCadence
    observation_semantics: ObservationSemantics
    revision_policy: str = ""
    pit_eligibility_rule: str = ""
    source_confidence: SourceConfidence
    data_quality_multipliers: DataQualityMultipliers = Field(default_factory=DataQualityMultipliers)

    @model_validator(mode="after")
    def _check_time_format(self) -> ReleaseCalendar:
        t = self.release_cadence.earliest_release_time_et
        if len(t) != 5 or t[2] != ":":
            raise ValueError(f"earliest_release_time_et must be HH:MM, got {t!r}")
        hh, mm = t.split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError(f"invalid earliest_release_time_et: {t}")
        return self

    # -- eligibility predicate -----------------------------------------------

    def is_eligible(self, release_ts: datetime, as_of_ts: datetime) -> bool:
        """PIT eligibility: release_ts <= as_of_ts in UTC.

        (Supersession-aware eligibility is in PITReader.as_of; this
        predicate is for raw temporal ordering only.)
        """
        r = _to_utc(release_ts)
        t = _to_utc(as_of_ts)
        return r <= t

    def quality_multiplier_for_lag(self, lag_days: float) -> float:
        m = self.data_quality_multipliers
        if lag_days <= 7:
            return m.fresh
        if lag_days <= 14:
            return m.stale_1week
        if lag_days <= 28:
            return m.stale_2week
        return m.stale_over_2week


def load_calendar(path: Path) -> ReleaseCalendar:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"calendar YAML must be a mapping, got {type(raw).__name__}")
    return ReleaseCalendar.model_validate(raw)


def load_calendars_dir(path: Path) -> dict[str, ReleaseCalendar]:
    """Load every *.yaml in `path`, keyed by declared source."""
    calendars: dict[str, ReleaseCalendar] = {}
    for p in sorted(Path(path).glob("*.yaml")):
        cal = load_calendar(p)
        if cal.source in calendars:
            raise ValueError(
                f"duplicate calendar source {cal.source!r} "
                f"at {p} (also at {calendars[cal.source].source})"
            )
        calendars[cal.source] = cal
    return calendars


def _to_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)
