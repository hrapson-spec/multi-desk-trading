"""Scoring primitive tests."""

from __future__ import annotations

import numpy as np
import pytest

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS
from v2.eval import (
    approx_crps_from_quantiles,
    diebold_mariano_hac,
    interval_coverage,
    mean_pinball_loss,
    moving_block_bootstrap,
    pinball_loss,
)

_LEVELS = np.array(FIXED_QUANTILE_LEVELS)


# ---------------- pinball ----------------


def test_pinball_zero_at_perfect_forecast():
    y = np.array([0.0])
    # Degenerate distribution at 0 (all quantiles = 0).
    q = np.zeros((1, len(_LEVELS)))
    loss = pinball_loss(y, q, _LEVELS)
    assert np.allclose(loss, 0.0)


def test_pinball_formula():
    y = np.array([1.0])
    q = np.array([[0.0] * len(_LEVELS)])  # all quantiles at 0
    loss = pinball_loss(y, q, _LEVELS)
    # For y > q: loss = τ · (y - q) = τ · 1.
    assert np.allclose(loss[0], _LEVELS)


def test_mean_pinball_equals_mean_of_per_obs_per_level():
    rng = np.random.default_rng(42)
    y = rng.normal(size=50)
    q = np.sort(rng.normal(scale=0.5, size=(50, len(_LEVELS))), axis=1)
    expected = pinball_loss(y, q, _LEVELS).mean()
    assert mean_pinball_loss(y, q, _LEVELS) == pytest.approx(expected)


# ---------------- approx-CRPS ----------------


def test_approx_crps_positive_for_non_degenerate():
    rng = np.random.default_rng(0)
    y = rng.normal(size=100)
    q = np.tile(np.linspace(-1, 1, len(_LEVELS)), (100, 1))
    assert approx_crps_from_quantiles(y, q, _LEVELS) > 0


def test_approx_crps_zero_for_perfect_point_forecast():
    y = np.array([0.5])
    q = np.full((1, len(_LEVELS)), 0.5)
    assert approx_crps_from_quantiles(y, q, _LEVELS) == pytest.approx(0.0, abs=1e-12)


# ---------------- coverage ----------------


def test_coverage_exact_for_on_grid_nominal():
    # Use nominal=0.90: (1-0.9)/2 = 0.05 is exactly on the v2 fixed grid,
    # so no interpolation bias.
    rng = np.random.default_rng(1)
    n = 5_000
    y = rng.standard_normal(n)
    from scipy.stats import norm as _norm

    q = np.tile([_norm.ppf(t) for t in _LEVELS], (n, 1))
    report = interval_coverage(y, q, _LEVELS, nominal=0.90)
    assert report.nominal == 0.90
    assert abs(report.empirical - 0.90) < 0.02
    assert report.n == n


def test_coverage_off_grid_nominal_is_biased_but_usable():
    # nominal=0.80 requires τ=0.10 and τ=0.90, neither on the v2 grid.
    # Linear interpolation between (0.05, Φ⁻¹(0.05)) and (0.25, Φ⁻¹(0.25))
    # produces a systematically wider lower bound → higher empirical
    # coverage than nominal. This is expected and documented.
    rng = np.random.default_rng(7)
    n = 5_000
    y = rng.standard_normal(n)
    from scipy.stats import norm as _norm

    q = np.tile([_norm.ppf(t) for t in _LEVELS], (n, 1))
    report = interval_coverage(y, q, _LEVELS, nominal=0.80)
    # Empirical ~0.84 due to interpolation bias; must still strictly
    # exceed 0.5 (sanity) and undershoot 0.95 (not degenerate).
    assert 0.78 <= report.empirical <= 0.95


def test_coverage_narrow_forecast_undercovers():
    rng = np.random.default_rng(2)
    n = 2_000
    y = rng.standard_normal(n)
    from scipy.stats import norm as _norm

    q = np.tile([0.3 * _norm.ppf(t) for t in _LEVELS], (n, 1))
    report = interval_coverage(y, q, _LEVELS, nominal=0.90)
    assert report.empirical < 0.90


def test_coverage_nominal_outside_grid_rejected():
    rng = np.random.default_rng(8)
    n = 100
    y = rng.standard_normal(n)
    q = np.zeros((n, len(_LEVELS)))
    # nominal=0.999 requires τ=0.0005 which is below the grid's 0.01.
    with pytest.raises(ValueError):
        interval_coverage(y, q, _LEVELS, nominal=0.999)


# ---------------- Diebold–Mariano ----------------


def test_dm_positive_mean_diff_when_a_worse():
    rng = np.random.default_rng(3)
    n = 200
    a = rng.standard_normal(n) + 1.0  # higher mean loss
    b = rng.standard_normal(n)
    res = diebold_mariano_hac(a, b)
    assert res.mean_diff > 0
    assert res.dm_stat > 0
    assert res.n == n


def test_dm_lag_default_rises_with_n():
    rng = np.random.default_rng(4)
    a = rng.standard_normal(50)
    b = rng.standard_normal(50)
    r1 = diebold_mariano_hac(a, b)
    a2 = rng.standard_normal(5_000)
    b2 = rng.standard_normal(5_000)
    r2 = diebold_mariano_hac(a2, b2)
    assert r2.lag >= r1.lag


def test_dm_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        diebold_mariano_hac(np.zeros(5), np.zeros(6))


def test_dm_too_short_rejected():
    with pytest.raises(ValueError):
        diebold_mariano_hac(np.zeros(2), np.zeros(2))


# ---------------- block bootstrap ----------------


def test_bootstrap_ci_contains_mean():
    rng = np.random.default_rng(5)
    s = rng.standard_normal(500)
    ci = moving_block_bootstrap(s, block_size=10, n_boot=300, seed=99)
    assert ci.lower <= ci.mean <= ci.upper
    assert ci.block_size == 10
    assert ci.n_boot == 300


def test_bootstrap_rejects_bad_block_size():
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.zeros(10), block_size=0, n_boot=100)
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.zeros(10), block_size=11, n_boot=100)


def test_bootstrap_rejects_bad_ci():
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.zeros(10), block_size=2, n_boot=100, ci=1.5)
