"""Scoring primitives for Layer-3 forecast validity.

All functions are pure: inputs in, arrays/scalars out. Higher-level
walk-forward drivers (B5b) coordinate these across refit blocks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# Pinball (quantile) loss
# ---------------------------------------------------------------------------


def pinball_loss(y: np.ndarray, q_hat: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """Per-observation, per-level pinball loss.

    Shapes:
        y: (N,)
        q_hat: (N, K) or (K,)
        levels: (K,)
    Returns:
        (N, K) array: ρ_τ(y - q̂)
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    q_hat = np.asarray(q_hat, dtype=float)
    levels = np.asarray(levels, dtype=float).reshape(-1)
    if q_hat.ndim == 1:
        q_hat = np.broadcast_to(q_hat, (y.shape[0], q_hat.shape[0])).copy()
    if q_hat.shape != (y.shape[0], levels.shape[0]):
        raise ValueError(
            f"pinball_loss shape mismatch: y={y.shape}, q_hat={q_hat.shape}, levels={levels.shape}"
        )
    error = y[:, None] - q_hat
    loss = np.where(error >= 0, levels * error, (levels - 1.0) * error)
    return loss


def mean_pinball_loss(y: np.ndarray, q_hat: np.ndarray, levels: np.ndarray) -> float:
    """Scalar: mean over observations AND quantile levels."""
    return float(pinball_loss(y, q_hat, levels).mean())


# ---------------------------------------------------------------------------
# Approximate CRPS from a finite quantile grid
# ---------------------------------------------------------------------------


def approx_crps_from_quantiles(y: np.ndarray, q_hat: np.ndarray, levels: np.ndarray) -> float:
    """Approximation of CRPS from a piecewise-linear CDF through (q, level).

    Identity: CRPS(F, y) = 2 * ∫_0^1 ρ_τ(y - F⁻¹(τ)) dτ.
    With a finite level grid we approximate the integral by the trapezoidal
    rule over levels.

    This is the standard quantile-based CRPS approximation used when only
    a fixed grid is available.
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    q_hat = np.asarray(q_hat, dtype=float)
    levels = np.asarray(levels, dtype=float).reshape(-1)
    if q_hat.ndim == 1:
        q_hat = np.broadcast_to(q_hat, (y.shape[0], q_hat.shape[0])).copy()

    losses = pinball_loss(y, q_hat, levels)  # (N, K)
    # Trapezoidal integration over levels of 2 * pinball_loss.
    # np.trapz expects level-axis values.
    crps_per_obs = 2.0 * np.trapezoid(losses, x=levels, axis=1)
    return float(crps_per_obs.mean())


# ---------------------------------------------------------------------------
# Interval coverage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CoverageReport:
    nominal: float
    empirical: float
    avg_width: float
    n: int


def interval_coverage(
    y: np.ndarray,
    q_hat: np.ndarray,
    levels: np.ndarray,
    *,
    nominal: float = 0.80,
) -> CoverageReport:
    """Empirical coverage of the symmetric interval at `nominal` level.

    When (1-nominal)/2 or 1-(1-nominal)/2 is not present on the supplied
    grid, the bounds are linearly interpolated between adjacent levels
    (piecewise-linear CDF between grid points). This lets Layer-3
    promotion hurdles be checked at arbitrary nominal levels without
    changing the fixed grid.
    """
    y = np.asarray(y, dtype=float).reshape(-1)
    q_hat = np.asarray(q_hat, dtype=float)
    if q_hat.ndim == 1:
        q_hat = np.broadcast_to(q_hat, (y.shape[0], q_hat.shape[0])).copy()
    levels = np.asarray(levels, dtype=float).reshape(-1)

    lower_tau = (1.0 - nominal) / 2.0
    upper_tau = 1.0 - lower_tau
    if lower_tau < levels.min() or upper_tau > levels.max():
        raise ValueError(
            f"nominal={nominal} requires τ∈[{lower_tau}, {upper_tau}] "
            f"but grid only spans [{levels.min()}, {levels.max()}]"
        )
    # np.interp linearly interpolates q_hat (N, K) along the K axis.
    lower = np.array([np.interp(lower_tau, levels, row) for row in q_hat])
    upper = np.array([np.interp(upper_tau, levels, row) for row in q_hat])
    inside = (y >= lower) & (y <= upper)
    return CoverageReport(
        nominal=nominal,
        empirical=float(inside.mean()),
        avg_width=float((upper - lower).mean()),
        n=int(y.shape[0]),
    )


# ---------------------------------------------------------------------------
# Diebold–Mariano with HAC (Newey–West) variance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DMResult:
    mean_diff: float
    variance_hac: float
    dm_stat: float
    lag: int
    n: int


def diebold_mariano_hac(
    losses_a: np.ndarray,
    losses_b: np.ndarray,
    *,
    lag: int | None = None,
) -> DMResult:
    """DM test comparing two loss series under HAC (Newey–West) variance.

    d_t = L_a(t) - L_b(t). H0: E[d] = 0. Under HAC with truncation lag h,

        Var(d̄) ≈ (γ_0 + 2 Σ_{k=1..h} (1 - k/(h+1)) γ_k) / n

    dm_stat = d̄ / √Var(d̄). Asymptotically N(0, 1).
    Negative dm_stat means L_a is smaller (model A is better).

    If `lag` is None, defaults to floor(4 * (n/100)^(2/9)) (Newey–West rule
    of thumb) with a lower bound of 1.
    """
    a = np.asarray(losses_a, dtype=float).reshape(-1)
    b = np.asarray(losses_b, dtype=float).reshape(-1)
    if a.shape != b.shape:
        raise ValueError(f"loss shape mismatch: {a.shape} vs {b.shape}")
    n = a.shape[0]
    if n < 3:
        raise ValueError("diebold_mariano_hac requires at least 3 observations")

    d = a - b
    d_bar = float(d.mean())
    d_c = d - d_bar

    if lag is None:
        lag = max(1, int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0))))

    # Auto-covariance γ_k.
    gamma_0 = float((d_c * d_c).mean())
    var = gamma_0
    for k in range(1, lag + 1):
        if k >= n:
            break
        gamma_k = float((d_c[k:] * d_c[:-k]).mean())
        weight = 1.0 - k / (lag + 1.0)
        var += 2.0 * weight * gamma_k
    var_d_bar = max(var, 1e-18) / n
    dm_stat = d_bar / np.sqrt(var_d_bar)
    return DMResult(
        mean_diff=d_bar,
        variance_hac=var_d_bar,
        dm_stat=float(dm_stat),
        lag=lag,
        n=n,
    )


# ---------------------------------------------------------------------------
# Moving-block bootstrap CI on a mean
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BootstrapCI:
    mean: float
    lower: float
    upper: float
    n_boot: int
    block_size: int


def moving_block_bootstrap(
    series: np.ndarray,
    *,
    block_size: int,
    n_boot: int = 1000,
    ci: float = 0.95,
    seed: int | None = None,
) -> BootstrapCI:
    """Moving-block bootstrap CI on the mean of an autocorrelated series.

    Used for Layer-3 confidence on loss differentials when DM's normal
    approximation is unstable (small N, heavy tails).
    """
    s = np.asarray(series, dtype=float).reshape(-1)
    n = s.shape[0]
    if block_size <= 0 or block_size > n:
        raise ValueError(f"block_size must be in (0, {n}], got {block_size}")
    if n_boot <= 0:
        raise ValueError("n_boot must be > 0")
    if not 0 < ci < 1:
        raise ValueError("ci must be in (0, 1)")

    rng = np.random.default_rng(seed)
    n_blocks = int(np.ceil(n / block_size))
    starts_pool = np.arange(0, n - block_size + 1)
    means = np.empty(n_boot, dtype=float)
    for i in range(n_boot):
        starts = rng.choice(starts_pool, size=n_blocks, replace=True)
        sample = np.concatenate([s[st : st + block_size] for st in starts])[:n]
        means[i] = sample.mean()
    alpha = 1.0 - ci
    lower, upper = np.quantile(means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return BootstrapCI(
        mean=float(s.mean()),
        lower=float(lower),
        upper=float(upper),
        n_boot=n_boot,
        block_size=block_size,
    )
