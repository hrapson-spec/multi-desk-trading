"""Execution layer.

Three pure mechanisms at B6a:
    control_law — maps a FamilyForecast to a target risk budget b_t.
    adapter     — maps b_t to discrete lot count for execution.
    degradation — four-state ladder governing when to rebalance, hold,
                  decay, or force-flat.

The stateful simulator + paper-live loop land in B6b.
"""

from v2.execution.adapter import AdapterParams, TargetLotResult, target_lots
from v2.execution.control_law import ControlLawParams, compute_target_risk_budget
from v2.execution.degradation import ExposureState, TickEvent, step
from v2.execution.simulator import (
    DecisionRecord,
    InternalSimulator,
    LedgerRecord,
    RuntimeLedgerConflict,
)

__all__ = [
    "AdapterParams",
    "ControlLawParams",
    "DecisionRecord",
    "ExposureState",
    "InternalSimulator",
    "LedgerRecord",
    "RuntimeLedgerConflict",
    "TargetLotResult",
    "TickEvent",
    "compute_target_risk_budget",
    "step",
    "target_lots",
]
