"""Baseline B0 / B1 tests."""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pytest
from scipy.stats import norm

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS
from v2.eval import B0EWMAGaussian, B1Empirical

# ---------------- B0 ----------------


def test_b0_emits_fixed_grid():
    b0 = B0EWMAGaussian(halflife_days=60)
    rng = np.random.default_rng(0)
    qv = b0.fit_predict(rng.standard_normal(500))
    assert len(qv) == len(FIXED_QUANTILE_LEVELS)


def test_b0_quantile_vector_is_monotone():
    b0 = B0EWMAGaussian(halflife_days=60)
    rng = np.random.default_rng(1)
    qv = b0.fit_predict(rng.standard_normal(500) * 0.02)
    for a, b in pairwise(qv):
        assert a <= b + 1e-12


def test_b0_sigma_matches_analytic_for_uniform_history():
    # If all returns are identical size σ, EWMA variance → σ²,
    # so q(0.95) ≈ σ · Φ⁻¹(0.95).
    sigma = 0.03
    history = np.full(200, sigma)  # constant |r|, so variance → σ².
    b0 = B0EWMAGaussian(halflife_days=60)
    qv = b0.fit_predict(history)
    q95 = qv[FIXED_QUANTILE_LEVELS.index(0.95)]
    expected = sigma * norm.ppf(0.95)
    assert abs(q95 - expected) < 1e-6


def test_b0_empty_history_rejected():
    with pytest.raises(ValueError):
        B0EWMAGaussian().fit_predict(np.array([]))


# ---------------- B1 ----------------


def test_b1_recovers_uniform_distribution_quantiles():
    # Uniform [0, 1] returns — empirical quantiles should approximate
    # the nominal levels.
    rng = np.random.default_rng(2)
    r = rng.uniform(0.0, 1.0, size=10_000)
    b1 = B1Empirical(window_years=100.0)  # no truncation
    qv = b1.fit_predict(r)
    for level, q in zip(FIXED_QUANTILE_LEVELS, qv, strict=True):
        assert abs(q - level) < 0.02


def test_b1_window_truncation_caps_history():
    rng = np.random.default_rng(3)
    r = rng.standard_normal(2_000)
    # Short window → last N observations dominate.
    b1_short = B1Empirical(window_years=1.0)
    qv_short = b1_short.fit_predict(r)
    b1_long = B1Empirical(window_years=10.0)
    qv_long = b1_long.fit_predict(r)
    # They should differ at least somewhere.
    assert qv_short != qv_long


def test_b1_time_decay_weights_recent_more_heavily():
    # Construct a series where recent values have larger magnitude.
    # Time-decayed B1 should produce wider quantiles than uniform.
    r = np.concatenate([np.zeros(500), np.linspace(0, 1, 100)])
    b1_uniform = B1Empirical(window_years=10.0, time_decay_halflife_days=None)
    b1_decay = B1Empirical(window_years=10.0, time_decay_halflife_days=20)
    q_uni = b1_uniform.fit_predict(r)
    q_dec = b1_decay.fit_predict(r)
    # q(0.95) of the decayed baseline should exceed the uniform baseline.
    idx_q95 = FIXED_QUANTILE_LEVELS.index(0.95)
    assert q_dec[idx_q95] > q_uni[idx_q95]


def test_b1_empty_history_rejected():
    with pytest.raises(ValueError):
        B1Empirical().fit_predict(np.array([]))
