"""v2 forecast + decision schemas.

Governed by docs/v2/v2_decision_contract.md. Fixed quantile grid:

    (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)

Action space (oil v2.0): target_risk_budget ∈ [-1, 1] ∪ {ABSTAIN}.
"""

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.decision_v2 import ActionType, DecisionV2, DegradationState
from v2.contracts.forecast_v2 import ForecastV2, SourceEligibility
from v2.contracts.target_variables import KNOWN_TARGETS, TargetSpec, lookup_target

__all__ = [
    "FIXED_QUANTILE_LEVELS",
    "KNOWN_TARGETS",
    "ActionType",
    "DecisionUnit",
    "DecisionV2",
    "DegradationState",
    "ForecastV2",
    "SourceEligibility",
    "TargetSpec",
    "lookup_target",
]
