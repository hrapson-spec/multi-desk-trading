"""Pre-registered monotone shadow decision rule.

    b̃_t = clip(k · Q̂(0.50) / max(σ̂_pred, σ_floor), -1, 1)

Used in Layer-3 challenger diagnostics (DSR / PBO via shadow returns)
and as a reference translation for Layer-4 cost-stress tests.

Explicitly NOT the family controller — that is a separate concern once
the synthesiser + execution adapter are wired. This rule is a fixed,
monotone translation of forecast → scalar target budget for auditing.
"""

from __future__ import annotations


def monotone_b_tilde(
    q50: float,
    sigma_pred: float,
    *,
    k: float = 1.0,
    sigma_floor: float = 0.01,
) -> float:
    """Monotone shadow rule.

    Args:
        q50: median of the family predictive distribution
             (family_quantile_vector[3] on the v2 grid).
        sigma_pred: predictive dispersion
                    (e.g. (q95 - q5) / (z95 - z5) ≈ 3.29).
        k: gain constant, pre-registered in the desk prereg.
        sigma_floor: minimum dispersion to avoid division blow-ups;
                     pre-registered.

    Returns:
        b̃ in [-1, 1].
    """
    if sigma_floor <= 0:
        raise ValueError("sigma_floor must be > 0")
    sigma = max(sigma_pred, sigma_floor)
    raw = k * q50 / sigma
    if raw > 1.0:
        return 1.0
    if raw < -1.0:
        return -1.0
    return float(raw)
