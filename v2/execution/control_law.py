"""Family-level control law: FamilyForecast → target risk budget b_t.

From v2_decision_contract §3.3:

    μ_t          = Q̂_family(0.50)
    σ̂_t^pred    = (Q̂(0.95) - Q̂(0.05)) / (z_{0.95} - z_{0.05})
    s_t          = μ_t / max(σ̂_t^pred, σ_floor)
    b_t          = clip(k · s_t · c_t · q_t · r_t, -1, 1)

where c_t / q_t / r_t are the calibration / data-quality / roll-liquidity
multipliers. On abstain, `compute_target_risk_budget` returns None; the
caller is responsible for translating that into an ABSTAIN decision
(or handing off to the degradation ladder).
"""

from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import norm

from v2.synthesiser import FamilyForecast

_Z_95 = float(norm.ppf(0.95))
_Z_05 = float(norm.ppf(0.05))
_Z_90_05_WIDTH = _Z_95 - _Z_05  # ≈ 3.2897


@dataclass(frozen=True)
class ControlLawParams:
    k: float = 1.0  # family gain
    sigma_floor: float = 0.01  # floor on σ̂_pred; > 0
    roll_liquidity_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.sigma_floor <= 0:
            raise ValueError("sigma_floor must be > 0")
        if not (0.0 <= self.roll_liquidity_multiplier <= 1.0):
            raise ValueError("roll_liquidity_multiplier must be in [0, 1]")


def compute_target_risk_budget(
    family: FamilyForecast,
    *,
    params: ControlLawParams,
    calibration_multiplier: float | None = None,
    data_quality_multiplier: float | None = None,
) -> float | None:
    """Return b_t ∈ [-1, 1], or None if the family abstained.

    Args:
        family: the synthesiser's output.
        params: control-law hyperparameters (pre-registered).
        calibration_multiplier: optional per-tick override. Defaults to
            the weighted average of contributing desks' calibration
            scores (pulled from family.contributing).
        data_quality_multiplier: optional per-tick override. Defaults
            to the weighted average of contributing data_quality_scores.
    """
    if family.abstain or family.quantile_vector is None:
        return None

    qv = family.quantile_vector
    # Fixed-grid indices: (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)
    q05 = qv[1]
    q50 = qv[3]
    q95 = qv[5]
    sigma_pred = (q95 - q05) / _Z_90_05_WIDTH
    sigma_eff = max(sigma_pred, params.sigma_floor)
    s = q50 / sigma_eff

    if calibration_multiplier is None:
        calibration_multiplier = _weighted_avg(
            [c.weight_normalised for c in family.contributing],
            [c.calibration_score for c in family.contributing],
        )
    if data_quality_multiplier is None:
        data_quality_multiplier = _weighted_avg(
            [c.weight_normalised for c in family.contributing],
            [c.data_quality_score for c in family.contributing],
        )

    raw = (
        params.k
        * s
        * calibration_multiplier
        * data_quality_multiplier
        * params.roll_liquidity_multiplier
    )
    if raw > 1.0:
        return 1.0
    if raw < -1.0:
        return -1.0
    return float(raw)


def _weighted_avg(weights: list[float], values: list[float]) -> float:
    if not weights or not values:
        return 1.0
    total = sum(weights)
    if total <= 0:
        return 1.0
    return sum(w * v for w, v in zip(weights, values, strict=True)) / total
