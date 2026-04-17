"""Forecast → Print matching and Grade emission (spec §4.7).

Matching function:
- EventHorizon: match on (target_variable, horizon.event_id).
- ClockHorizon: match on (target_variable) with
      |realised_ts_utc − (emission_ts_utc + duration)| ≤ tolerance.

Event-slip policy (locked in spec §4.7):
- Grade fires on actual Print arrival.
- expected_ts_utc on the Forecast never mutates post-emission.
- realised_ts_utc − expected_ts_utc is recorded in schedule_slip_seconds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from math import isnan
from typing import Any

from contracts.v1 import ClockHorizon, EventHorizon, Forecast, Grade, Print

DEFAULT_CLOCK_TOLERANCE = timedelta(hours=6)


def matches(
    forecast: Forecast,
    p: Print,
    tolerance: timedelta = DEFAULT_CLOCK_TOLERANCE,
) -> bool:
    """Return True iff the Forecast and Print should be graded together."""
    if forecast.target_variable != p.target_variable:
        return False
    if isinstance(forecast.horizon, EventHorizon):
        return p.event_id == forecast.horizon.event_id
    if isinstance(forecast.horizon, ClockHorizon):
        expected = forecast.emission_ts_utc + forecast.horizon.duration
        return abs((p.realised_ts_utc - expected).total_seconds()) <= tolerance.total_seconds()
    raise TypeError(f"unsupported horizon kind: {type(forecast.horizon).__name__}")


def _now_utc() -> datetime:
    return datetime.now(tz=UTC)


def grade(
    forecast: Forecast,
    p: Print,
    *,
    grading_ts_utc: datetime | None = None,
) -> Grade:
    """Compute a Grade from a matched Forecast × Print pair.

    Pure function: given the same inputs, always returns byte-identical
    outputs except grading_ts_utc; inject grading_ts_utc from the caller
    in replay contexts for full determinism.
    """
    ts = grading_ts_utc if grading_ts_utc is not None else _now_utc()
    err = p.value - forecast.point_estimate
    squared_error = err * err
    absolute_error = abs(err)

    # sign_agreement: directional_claim sign vs realised direction
    # implied by the sign of err. 'none' claims do not have a checkable
    # direction and return None.
    sign_agreement: bool | None
    if forecast.directional_claim.sign == "none":
        sign_agreement = None
    else:
        # Convention: positive claim = "value will rise above point_estimate"
        # i.e. realised > point_estimate aligns with positive claim.
        realised_direction = "positive" if err > 0 else ("negative" if err < 0 else None)
        if realised_direction is None:
            sign_agreement = None
        else:
            sign_agreement = realised_direction == forecast.directional_claim.sign

    u = forecast.uncertainty
    within_uncertainty: bool | None = (
        None if isnan(u.lower) or isnan(u.upper) else u.lower <= p.value <= u.upper
    )

    schedule_slip_seconds: float | None = None
    if isinstance(forecast.horizon, EventHorizon):
        slip = (p.realised_ts_utc - forecast.horizon.expected_ts_utc).total_seconds()
        schedule_slip_seconds = float(slip)

    return Grade(
        grade_id=str(uuid.uuid4()),
        forecast_id=forecast.forecast_id,
        print_id=p.print_id,
        grading_ts_utc=ts,
        squared_error=float(squared_error),
        absolute_error=float(absolute_error),
        log_score=None,  # populated by probabilistic-forecast extension
        sign_agreement=sign_agreement,
        within_uncertainty=within_uncertainty,
        schedule_slip_seconds=schedule_slip_seconds,
    )


def grade_pairs(
    pairs: list[tuple[Forecast, Print]],
    *,
    grading_ts_utc: datetime | None = None,
    tolerance: timedelta = DEFAULT_CLOCK_TOLERANCE,
) -> list[Grade]:
    """Grade a batch of pre-matched (Forecast, Print) pairs.

    Caller is responsible for ensuring each pair satisfies `matches()`;
    this function asserts that as a defensive check and emits Grades.
    """
    out: list[Grade] = []
    for f, p in pairs:
        if not matches(f, p, tolerance=tolerance):
            raise ValueError(
                f"forecast {f.forecast_id} does not match print {p.print_id} "
                f"(target_variable mismatch or horizon out of tolerance)"
            )
        out.append(grade(f, p, grading_ts_utc=grading_ts_utc))
    return out


__all__: list[str] = ["matches", "grade", "grade_pairs", "DEFAULT_CLOCK_TOLERANCE"]


# type: ignore — Any import retained for future probabilistic-forecast extension
_ = Any
