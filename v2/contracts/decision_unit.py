"""Decision unit enum + fixed quantile grid.

These two are contract-level constants referenced by every v2 ForecastV2
and DecisionV2. Neither may be mutated within a given contract_version;
a change here requires a v2.x bump and the associated governance
artefact updates.
"""

from __future__ import annotations

from enum import StrEnum


class DecisionUnit(StrEnum):
    """Canonical units of a family's decision output.

    Mixed units are forbidden inside a single family synthesiser
    (docs/v2/v2_decision_contract.md §7 Forbidden).
    """

    LOG_RETURN = "log_return"
    SPREAD_CHANGE = "spread_change"
    VOL_POINT_CHANGE = "vol_point_change"
    UTILITY = "utility"


FIXED_QUANTILE_LEVELS: tuple[float, ...] = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
"""Every ForecastV2 MUST emit this grid. Other grids are contract failures."""
