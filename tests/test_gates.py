"""Unit tests for eval/gates.py.

Verifies the three hard gates under controlled synthetic conditions:
  - gate_skill_vs_baseline detects an oracle-ish forecaster beating persistence
  - gate_sign_preservation catches sign-flip dev→test (Kronos-RCA pattern)
  - gate_hot_swap surfaces exceptions raised under either configuration
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from eval import (
    GateReport,
    gate_hot_swap,
    gate_sign_preservation,
    gate_skill_vs_baseline,
)
from eval.data import make_forecasts_and_prints, persistence_baseline


def test_gate1_oracle_beats_persistence():
    fcasts, prints, _ = make_forecasts_and_prints(
        n=50,
        start_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
        seed=1,
        forecast_generator="noisy_truth",
    )
    result = gate_skill_vs_baseline(fcasts, prints, persistence_baseline, metric="rmse")
    assert result.passed, result.reason
    assert result.metrics["desk_metric"] < result.metrics["baseline_metric"]


def test_gate1_stub_zero_fails_persistence():
    fcasts, prints, _ = make_forecasts_and_prints(
        n=50,
        start_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
        seed=2,
        forecast_generator="zero",
    )
    result = gate_skill_vs_baseline(fcasts, prints, persistence_baseline, metric="rmse")
    assert not result.passed, result.reason


def test_gate2_aligned_dev_and_test_passes():
    rng = np.random.default_rng(42)
    # Oracle-ish: scores and outcomes share a latent signal.
    true = rng.normal(0, 1, 200)
    dev_scores = true[:100] + rng.normal(0, 0.1, 100)
    dev_outcomes = true[:100]
    test_scores = true[100:] + rng.normal(0, 0.1, 100)
    test_outcomes = true[100:]
    result = gate_sign_preservation(
        dev_directional_scores=list(dev_scores),
        dev_forward_outcomes=list(dev_outcomes),
        test_directional_scores=list(test_scores),
        test_forward_outcomes=list(test_outcomes),
        expected_sign="positive",
    )
    assert result.passed, result.reason
    assert result.metrics["dev_rho"] > 0
    assert result.metrics["test_rho"] > 0


def test_gate2_sign_flip_dev_to_test_fails():
    """The Kronos-RCA pattern: positive on dev, negative on test."""
    rng = np.random.default_rng(42)
    n = 100
    dev_scores = rng.normal(0, 1, n).tolist()
    dev_outcomes = [s + float(rng.normal(0, 0.1)) for s in dev_scores]  # +ve rho
    test_scores = rng.normal(0, 1, n).tolist()
    test_outcomes = [-s + float(rng.normal(0, 0.1)) for s in test_scores]  # -ve rho
    result = gate_sign_preservation(
        dev_directional_scores=dev_scores,
        dev_forward_outcomes=dev_outcomes,
        test_directional_scores=test_scores,
        test_forward_outcomes=test_outcomes,
        expected_sign="positive",
    )
    assert not result.passed, result.reason
    assert "KRONOS-RCA PATTERN" in result.reason


def test_gate2_rejects_expected_sign_mismatch_on_dev():
    """Desk declared 'positive' but dev ρ is strongly negative."""
    rng = np.random.default_rng(42)
    n = 100
    dev_scores = rng.normal(0, 1, n).tolist()
    dev_outcomes = [-s + float(rng.normal(0, 0.1)) for s in dev_scores]
    test_scores = rng.normal(0, 1, n).tolist()
    test_outcomes = [-s + float(rng.normal(0, 0.1)) for s in test_scores]
    result = gate_sign_preservation(
        dev_directional_scores=dev_scores,
        dev_forward_outcomes=dev_outcomes,
        test_directional_scores=test_scores,
        test_forward_outcomes=test_outcomes,
        expected_sign="positive",
    )
    assert not result.passed, result.reason


def test_gate3_both_paths_pass():
    """Shell unit test: both closures return True → gate passes with
    failure_mode='passed'. Legitimately uses `lambda: True` because
    this tests the SHELL's pass-through behaviour, not integration.
    Integration tests use eval.build_hot_swap_callables (spec v1.14)."""
    result = gate_hot_swap(
        run_controller_fn=lambda: True,
        run_controller_with_stub_fn=lambda: True,
    )
    assert result.passed, result.reason
    assert result.metrics["real_ok"] == 1.0
    assert result.metrics["stub_ok"] == 1.0
    assert result.metrics["failure_mode"] == "passed"


def test_gate3_real_desk_raises():
    """Shell unit test: real-side closure raises RuntimeError →
    failure_mode='controller_exception'."""

    def _raise():
        raise RuntimeError("real desk broke Controller")

    result = gate_hot_swap(
        run_controller_fn=_raise,
        run_controller_with_stub_fn=lambda: True,
    )
    assert not result.passed
    assert "real desk broke Controller" in result.reason
    assert result.metrics["failure_mode"] == "controller_exception"


def test_gate3_stub_swap_breaks():
    """Shell unit test: stub-side closure raises RuntimeError →
    failure_mode='controller_exception'."""

    def _raise():
        raise RuntimeError("stub broke Controller")

    result = gate_hot_swap(
        run_controller_fn=lambda: True,
        run_controller_with_stub_fn=_raise,
    )
    assert not result.passed
    assert "stub broke Controller" in result.reason
    assert result.metrics["failure_mode"] == "controller_exception"


def test_gate3_assertion_in_closure_fails():
    """Shell unit test (M-1): closure raises AssertionError (the path
    build_hot_swap_callables uses for post-exercise invariant violations)
    → failure_mode='assertion_failure'. Distinguishes harness-assertion
    failures from genuine Controller integration bugs."""

    def _assert_fail():
        raise AssertionError("combined_signal delta mismatch: got X expected Y")

    # Real side asserts.
    result = gate_hot_swap(
        run_controller_fn=_assert_fail,
        run_controller_with_stub_fn=lambda: True,
    )
    assert not result.passed
    assert result.metrics["failure_mode"] == "assertion_failure"
    assert "Real-desk closure assertion failed" in result.reason

    # Stub side asserts.
    result = gate_hot_swap(
        run_controller_fn=lambda: True,
        run_controller_with_stub_fn=_assert_fail,
    )
    assert not result.passed
    assert result.metrics["failure_mode"] == "assertion_failure"
    assert "Stub-swap closure assertion failed" in result.reason


def test_gate_report_all_passed_aggregates():
    from eval.gates import GateResult

    report = GateReport(
        desk_name="t",
        gate1_skill=GateResult(name="s", passed=True),
        gate2_sign_preservation=GateResult(name="sp", passed=True),
        gate3_hot_swap=GateResult(name="hs", passed=True),
    )
    assert report.all_passed

    report2 = GateReport(
        desk_name="t",
        gate1_skill=GateResult(name="s", passed=True),
        gate2_sign_preservation=GateResult(name="sp", passed=False),
        gate3_hot_swap=GateResult(name="hs", passed=True),
    )
    assert not report2.all_passed
