"""Layer-4 two-scenario cost stress.

Two scenarios applied to the same position path:

    OPTIMISTIC: fixed-bps one-way slippage + exchange fee per contract.
    PESSIMISTIC: 3 × vol-scaled bps slippage + sqrt-size market impact.

Promotion requires positive expected utility under PESSIMISTIC.

The model consumes a sequence of (position_before, position_after, price,
realised_vol, realised_return) tuples and returns per-tick cost, turnover,
and net-return decomposition. It is intentionally PIT-safe: realised_vol
and realised_return must be values observable AT OR BEFORE the tick they
are applied to (the driver handles that ordering).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np


class CostScenario(StrEnum):
    OPTIMISTIC = "optimistic"
    PESSIMISTIC = "pessimistic"


@dataclass(frozen=True)
class CostParams:
    scenario: CostScenario
    fixed_bps_one_way: float  # optimistic: e.g. 1.5 bps
    exchange_fee_per_contract: float  # USD, e.g. 2.0 for CME CL
    vol_scale_coeff: float  # pessimistic: slippage = coeff × realised_vol
    sqrt_size_impact_coeff: float  # pessimistic: impact = coeff × sqrt(|Δsize|)

    @classmethod
    def optimistic_default(cls) -> CostParams:
        return cls(
            scenario=CostScenario.OPTIMISTIC,
            fixed_bps_one_way=1.5,
            exchange_fee_per_contract=2.0,
            vol_scale_coeff=0.0,
            sqrt_size_impact_coeff=0.0,
        )

    @classmethod
    def pessimistic_default(cls) -> CostParams:
        return cls(
            scenario=CostScenario.PESSIMISTIC,
            fixed_bps_one_way=4.5,  # 3× optimistic
            exchange_fee_per_contract=2.0,
            vol_scale_coeff=0.30,  # 30% of realised-vol as bps per unit size
            sqrt_size_impact_coeff=0.15,  # 15 bps per √lot
        )


@dataclass(frozen=True)
class CostReport:
    scenario: CostScenario
    gross_return_total: float
    cost_total: float
    net_return_total: float
    turnover_total: float
    net_returns: np.ndarray  # per-tick net returns (length n_ticks)
    costs: np.ndarray  # per-tick absolute cost (same length)


def apply_costs(
    *,
    positions_before: np.ndarray,  # fraction-of-sleeve or lot-units
    positions_after: np.ndarray,
    gross_returns: np.ndarray,  # per-tick underlying return
    realised_vols: np.ndarray,  # per-tick annualised or horizon vol
    params: CostParams,
) -> CostReport:
    """Apply `params` costs to the position path.

    All inputs same length N. Returns a per-tick cost and net-return array.
    `gross_returns[t]` is the return earned by `positions_after[t-1]` over
    the (t-1, t] interval; the tick at t pays costs on the (t-1 → t) change.

    Units:
        positions_*: unitless (fraction of a unit-vol sleeve) or lots;
                     the cost is applied per unit traded.
        gross_returns: log return or simple return on the underlying;
                       output net_returns is in the same unit.
    """
    pb = np.asarray(positions_before, dtype=float).reshape(-1)
    pa = np.asarray(positions_after, dtype=float).reshape(-1)
    gr = np.asarray(gross_returns, dtype=float).reshape(-1)
    rv = np.asarray(realised_vols, dtype=float).reshape(-1)
    if not (pb.shape == pa.shape == gr.shape == rv.shape):
        raise ValueError(
            f"shape mismatch: pb={pb.shape}, pa={pa.shape}, gr={gr.shape}, rv={rv.shape}"
        )

    delta = np.abs(pa - pb)
    bps_fixed = params.fixed_bps_one_way / 10_000.0
    bps_vol = params.vol_scale_coeff * rv
    bps_impact = params.sqrt_size_impact_coeff * np.sqrt(delta) / 10_000.0
    # Slippage cost per tick = slippage_bps × traded_size (proxy for notional).
    slippage = (bps_fixed + bps_vol + bps_impact) * delta
    fee = params.exchange_fee_per_contract * delta  # proxy: 1 fee per unit-size change
    # For a unit-of-sleeve position path, fee_per_contract is interpreted as
    # a per-unit-size cost. The driver converts lots at the execution layer.
    costs = slippage + fee
    net = gr * pb - costs  # P&L earned on pre-trade position minus costs

    return CostReport(
        scenario=params.scenario,
        gross_return_total=float((gr * pb).sum()),
        cost_total=float(costs.sum()),
        net_return_total=float(net.sum()),
        turnover_total=float(delta.sum()),
        net_returns=net,
        costs=costs,
    )
