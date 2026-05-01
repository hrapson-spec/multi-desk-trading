"""v2 target-variable registry.

Every ForecastV2 and DecisionV2 cites a `target_variable` that MUST be
registered here. Adding a new target is a v2.x contract revision and
requires the prereg of whichever desk introduces it to pin the exact
TargetSpec.

The v1 registry at `contracts/target_variables.py` is a separate object
and remains frozen under CLAUDE.md's v1 frozen-surface discipline. The
v2 registry intentionally duplicates the names of the two v1 targets
(WTI_FRONT_1W_LOG_RETURN, VIX_30D_FORWARD_3D_DELTA) so that v2 desks
never reach into v1 code.
"""

from __future__ import annotations

from dataclasses import dataclass

from v2.contracts.decision_unit import DecisionUnit


@dataclass(frozen=True)
class TargetSpec:
    name: str
    decision_unit: DecisionUnit
    horizon: str
    instrument_spec: str  # human-readable; detailed instrument registry is pending


KNOWN_TARGETS: dict[str, TargetSpec] = {
    "WTI_FRONT_1W_LOG_RETURN": TargetSpec(
        name="WTI_FRONT_1W_LOG_RETURN",
        decision_unit=DecisionUnit.LOG_RETURN,
        horizon="5d",
        instrument_spec="WTI front-month futures under rolling_rule_v1",
    ),
    "VIX_30D_FORWARD_3D_DELTA": TargetSpec(
        name="VIX_30D_FORWARD_3D_DELTA",
        decision_unit=DecisionUnit.VOL_POINT_CHANGE,
        horizon="3d",
        instrument_spec="VIX 30-day forward under vix_forward_rule_v1",
    ),
}


class UnknownTargetError(KeyError):
    """Raised when a ForecastV2 or DecisionV2 cites a target not in KNOWN_TARGETS."""


def lookup_target(name: str) -> TargetSpec:
    if name not in KNOWN_TARGETS:
        raise UnknownTargetError(
            f"target_variable {name!r} is not in the v2 registry. "
            f"Known: {sorted(KNOWN_TARGETS.keys())}"
        )
    return KNOWN_TARGETS[name]
