"""Monotone shadow rule tests."""

from __future__ import annotations

import pytest

from v2.eval import monotone_b_tilde


def test_zero_signal_returns_zero():
    assert monotone_b_tilde(q50=0.0, sigma_pred=0.02) == 0.0


def test_positive_signal_positive_budget():
    assert monotone_b_tilde(q50=0.01, sigma_pred=0.02, k=1.0) > 0


def test_negative_signal_negative_budget():
    assert monotone_b_tilde(q50=-0.01, sigma_pred=0.02, k=1.0) < 0


def test_clipped_at_upper_bound():
    # k·q50/σ = 10 → clipped to 1.
    assert monotone_b_tilde(q50=0.20, sigma_pred=0.02, k=1.0) == 1.0


def test_clipped_at_lower_bound():
    assert monotone_b_tilde(q50=-0.20, sigma_pred=0.02, k=1.0) == -1.0


def test_sigma_floor_prevents_blow_up():
    # σ = 0 would otherwise divide by zero.
    v = monotone_b_tilde(q50=0.001, sigma_pred=0.0, k=1.0, sigma_floor=0.01)
    assert -1.0 <= v <= 1.0


def test_sigma_floor_must_be_positive():
    with pytest.raises(ValueError):
        monotone_b_tilde(q50=0.01, sigma_pred=0.02, sigma_floor=0.0)


def test_k_scales_proportionally():
    v1 = monotone_b_tilde(q50=0.005, sigma_pred=0.02, k=1.0)
    v2 = monotone_b_tilde(q50=0.005, sigma_pred=0.02, k=2.0)
    assert v2 == pytest.approx(2 * v1)
