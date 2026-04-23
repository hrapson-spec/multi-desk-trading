"""Strict family-input compatibility check.

Every forecast in a synthesiser call must agree on:
    - family_id
    - target_variable
    - target_horizon
    - decision_unit
    - quantile_levels (== FIXED_QUANTILE_LEVELS)
    - decision_ts

Any mismatch raises FamilyInputMismatchError. Mixed-unit aggregation is
the central failure mode v2 was designed to prevent; this check is the
place it fails loudly.
"""

from __future__ import annotations

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS
from v2.contracts.forecast_v2 import ForecastV2


class FamilyInputMismatchError(Exception):
    """Forecasts passed to the synthesiser do not share the required
    family invariants."""


def assert_compatible(forecasts: list[ForecastV2]) -> None:
    if not forecasts:
        raise FamilyInputMismatchError("synthesiser called with empty forecast list")

    ref = forecasts[0]
    for i, f in enumerate(forecasts[1:], start=1):
        if f.family_id != ref.family_id:
            raise FamilyInputMismatchError(
                f"family_id mismatch: index 0 has {ref.family_id!r}, index {i} has {f.family_id!r}"
            )
        if f.target_variable != ref.target_variable:
            raise FamilyInputMismatchError(
                f"target_variable mismatch: {ref.target_variable!r} vs {f.target_variable!r}"
            )
        if f.target_horizon != ref.target_horizon:
            raise FamilyInputMismatchError(
                f"target_horizon mismatch: {ref.target_horizon!r} vs {f.target_horizon!r}"
            )
        if f.decision_unit != ref.decision_unit:
            raise FamilyInputMismatchError(
                f"decision_unit mismatch: {ref.decision_unit} vs {f.decision_unit}"
            )
        if tuple(f.quantile_levels) != tuple(ref.quantile_levels):
            raise FamilyInputMismatchError(
                f"quantile_levels mismatch: {ref.quantile_levels} vs {f.quantile_levels}"
            )
        if f.decision_ts != ref.decision_ts:
            raise FamilyInputMismatchError(
                f"decision_ts mismatch: {ref.decision_ts.isoformat()} "
                f"vs {f.decision_ts.isoformat()}"
            )

    # Grid must be the canonical fixed grid (redundant with ForecastV2's
    # own validator, but explicit here for audit readability).
    if tuple(ref.quantile_levels) != FIXED_QUANTILE_LEVELS:
        raise FamilyInputMismatchError(
            f"quantile_levels {ref.quantile_levels} is not the canonical v2 grid"
        )
