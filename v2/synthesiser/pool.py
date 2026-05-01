"""CDF-space weighted linear pool.

Given (weight, quantile_vector) pairs sharing a fixed grid, compute the
pool's quantile vector on the same grid:

    F_family(y) = Σ_k w_k · F_k(y)
    quantile_family(τ) = inf { y : F_family(y) ≥ τ }

Each desk's CDF is piecewise-linear between (quantile[i], level[i]);
`numpy.interp` handles the interpolation with flat clipping at [0, 1]
outside the declared quantile range.
"""

from __future__ import annotations

import numpy as np

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS


def weighted_linear_pool_cdf(
    contributions: list[tuple[float, tuple[float, ...]]],
    *,
    target_levels: tuple[float, ...] = FIXED_QUANTILE_LEVELS,
    levels: tuple[float, ...] = FIXED_QUANTILE_LEVELS,
) -> tuple[float, ...]:
    """Combine per-desk quantile vectors via weighted linear pool on the CDF.

    Args:
        contributions: list of `(weight, quantile_vector)`. Weights must
            sum to 1.0 (caller renormalises). `quantile_vector` must be
            monotone non-decreasing and aligned with `levels`.
        target_levels: the output quantile levels (default: the v2 grid).
        levels: the input quantile levels (default: the v2 grid).

    Returns:
        Tuple of family quantile values aligned with `target_levels`.

    Raises:
        ValueError: contributions empty, weights do not sum to ~1.0, or
            any input vector fails monotonicity.
    """
    if not contributions:
        raise ValueError("weighted_linear_pool_cdf called with no contributions")

    weights = np.array([w for w, _ in contributions], dtype=float)
    if np.any(weights < 0):
        raise ValueError("weighted_linear_pool_cdf: negative weights")
    total = float(weights.sum())
    if not np.isclose(total, 1.0, atol=1e-9):
        raise ValueError(f"weighted_linear_pool_cdf: weights must sum to 1.0, got {total}")

    levels_arr = np.asarray(levels, dtype=float)
    target_arr = np.asarray(target_levels, dtype=float)

    vectors: list[np.ndarray] = []
    for _, qv in contributions:
        v = np.asarray(qv, dtype=float)
        if v.shape != levels_arr.shape:
            raise ValueError(
                f"quantile_vector of length {v.shape[0]} does not match "
                f"levels of length {levels_arr.shape[0]}"
            )
        if np.any(np.diff(v) < 0):
            raise ValueError("input quantile_vector must be monotone non-decreasing")
        vectors.append(v)

    # Union support: every distinct quantile value across all desks. Sort
    # ascending; adding extrapolation padding is unnecessary because the
    # level-clipping at [0, 1] below handles it.
    support = np.unique(np.concatenate(vectors))
    if support.size == 0:
        raise ValueError("empty support after union")

    # Family CDF at each support point: Σ w_k · F_k(support).
    # np.interp maps y → level (the CDF evaluation): given desk's
    # (quantile, level) pairs, F_k(y) is the interpolated level. Outside
    # the desk's declared quantile range we clip to [levels[0], levels[-1]]
    # — i.e. the desk's declared probability floor/ceiling.
    family_cdf = np.zeros_like(support, dtype=float)
    for w, v in zip(weights, vectors, strict=True):
        desk_cdf = np.interp(support, v, levels_arr, left=levels_arr[0], right=levels_arr[-1])
        family_cdf += w * desk_cdf

    # Invert at the target levels. np.interp with (x=target_levels,
    # xp=family_cdf, fp=support) returns y such that F_family(y) ≈ target.
    # family_cdf may have flat regions (zero-density), which np.interp
    # handles by returning the first support point satisfying the level.
    family_quantiles = np.interp(target_arr, family_cdf, support)

    return tuple(float(x) for x in family_quantiles)
