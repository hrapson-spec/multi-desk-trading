"""Execution adapter: b_t (target risk budget) → discrete lot count.

From v2_decision_contract §3.4:

    n*_lots = b_t · R_{5d,unit}^$ / (M · P_t · σ̂_5d,mkt)

where M is the contract multiplier (1 000 barrels for CL, 100 for MCL).
Rounding discretises the continuous optimum. The raw (unrounded) target
is returned alongside the rounded lots so the caller can log both for
audit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AdapterParams:
    reference_risk_5d_usd: float  # R_{5d,unit}^$ ; > 0
    contract_multiplier_bbl: float  # M ; e.g. 1000 for CL, 100 for MCL
    rounding: str = "nearest"  # "nearest" | "floor" | "ceil"
    max_abs_lots: int | None = None  # optional hard cap on |n_lots|

    def __post_init__(self) -> None:
        if self.reference_risk_5d_usd <= 0:
            raise ValueError("reference_risk_5d_usd must be > 0")
        if self.contract_multiplier_bbl <= 0:
            raise ValueError("contract_multiplier_bbl must be > 0")
        if self.rounding not in {"nearest", "floor", "ceil"}:
            raise ValueError(f"unknown rounding: {self.rounding!r}")


@dataclass(frozen=True)
class TargetLotResult:
    rounded_lots: int
    raw_lots: float
    effective_b: float  # the b_t actually expressible after rounding


def target_lots(
    *,
    b_t: float,
    price: float,
    market_vol_5d: float,
    params: AdapterParams,
) -> TargetLotResult:
    """Compute target lot count from target risk budget.

    Args:
        b_t: target risk budget in [-1, 1].
        price: front-month contract price (underlying quote).
        market_vol_5d: 5-day ex-ante log-return volatility of the
            underlying (unitless, e.g. 0.04 for 4%). NOT the predictive
            uncertainty — that is the forecast's concern.
        params: adapter configuration.

    Returns:
        TargetLotResult with rounded + raw lots + realised b.

    Raises:
        ValueError on invalid inputs.
    """
    if not (-1.0 <= b_t <= 1.0):
        raise ValueError(f"b_t must be in [-1, 1], got {b_t}")
    if price <= 0:
        raise ValueError(f"price must be > 0, got {price}")
    if market_vol_5d <= 0:
        raise ValueError(f"market_vol_5d must be > 0, got {market_vol_5d}")

    denom = params.contract_multiplier_bbl * price * market_vol_5d
    raw = b_t * params.reference_risk_5d_usd / denom

    if params.rounding == "nearest":
        rounded = int(round(raw))
    elif params.rounding == "floor":
        import math

        rounded = int(math.floor(raw))
    else:  # ceil
        import math

        rounded = int(math.ceil(raw))

    if params.max_abs_lots is not None:
        cap = params.max_abs_lots
        if rounded > cap:
            rounded = cap
        elif rounded < -cap:
            rounded = -cap

    # What b does this rounded lot count correspond to?
    effective_b = rounded * denom / params.reference_risk_5d_usd
    if effective_b > 1.0:
        effective_b = 1.0
    elif effective_b < -1.0:
        effective_b = -1.0

    return TargetLotResult(
        rounded_lots=rounded,
        raw_lots=float(raw),
        effective_b=float(effective_b),
    )
