"""CDF-space weighted linear pool tests."""

from __future__ import annotations

from itertools import pairwise

import pytest

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS
from v2.synthesiser import weighted_linear_pool_cdf


def test_single_desk_identity():
    qv = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    out = weighted_linear_pool_cdf([(1.0, qv)])
    # Single weight-1 desk must pool to itself.
    for a, b in zip(qv, out, strict=True):
        assert abs(a - b) < 1e-9


def test_two_identical_desks_equal_weights():
    qv = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    out = weighted_linear_pool_cdf([(0.5, qv), (0.5, qv)])
    for a, b in zip(qv, out, strict=True):
        assert abs(a - b) < 1e-9


def test_two_desks_disagreeing_means_widens_interval():
    # Desk A pessimistic, desk B optimistic — family 50/50 pool
    # should widen the 80% interval vs either desk alone.
    a = (-0.10, -0.07, -0.04, -0.02, 0.00, 0.02, 0.04)
    b = (-0.04, -0.02, 0.00, 0.02, 0.04, 0.07, 0.10)
    pool = weighted_linear_pool_cdf([(0.5, a), (0.5, b)])
    # IQR of the pool should exceed either input's IQR.
    iqr_a = a[-2] - a[1]
    iqr_b = b[-2] - b[1]
    iqr_pool = pool[-2] - pool[1]
    assert iqr_pool > iqr_a
    assert iqr_pool > iqr_b


def test_weights_not_summing_to_one_rejected():
    qv = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    with pytest.raises(ValueError, match="sum to 1.0"):
        weighted_linear_pool_cdf([(0.5, qv), (0.3, qv)])


def test_negative_weight_rejected():
    qv = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    with pytest.raises(ValueError, match="negative"):
        weighted_linear_pool_cdf([(1.2, qv), (-0.2, qv)])


def test_empty_contributions_rejected():
    with pytest.raises(ValueError):
        weighted_linear_pool_cdf([])


def test_mismatched_vector_length_rejected():
    qv_wrong = (-0.10, 0.0, 0.10)  # only 3 entries
    with pytest.raises(ValueError, match="match"):
        weighted_linear_pool_cdf([(1.0, qv_wrong)])


def test_non_monotone_input_rejected():
    qv_bad = (-0.10, -0.05, 0.10, 0.0, 0.02, 0.05, 0.08)
    with pytest.raises(ValueError, match="monotone"):
        weighted_linear_pool_cdf([(1.0, qv_bad)])


def test_pool_output_is_monotone():
    a = (-0.10, -0.07, -0.04, -0.02, 0.00, 0.02, 0.04)
    b = (-0.04, -0.02, 0.00, 0.02, 0.04, 0.07, 0.10)
    pool = weighted_linear_pool_cdf([(0.3, a), (0.7, b)])
    for x, y in pairwise(pool):
        assert x <= y + 1e-12


def test_output_grid_matches_target_levels():
    qv = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    out = weighted_linear_pool_cdf([(1.0, qv)])
    assert len(out) == len(FIXED_QUANTILE_LEVELS)
