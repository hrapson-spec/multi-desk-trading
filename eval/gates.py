"""Three hard-gate implementations (spec §7.1).

Each gate returns a GateResult with machine-readable pass/fail + metrics.
Gates are designed to be composable — a GateRunner (see runner.py) calls
each in sequence and aggregates into a GateReport.

Kronos V2 RCA lesson: Gate 2 sign preservation is the most load-bearing.
It caught the Kronos distribution-shift failure mechanism that would have
been invisible to Gate 1 skill alone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import spearmanr

from contracts.v1 import Forecast, Print


@dataclass
class GateResult:
    name: str
    passed: bool
    # metrics is heterogeneous: numeric keys like "desk_metric", "dev_rho",
    # plus string tags like "failure_mode" (spec v1.14 — see gate_hot_swap).
    # Consumers access specific known keys; treat as dict[str, object] at
    # read time and narrow per-key.
    metrics: dict[str, float | str] = field(default_factory=dict)
    reason: str = ""


@dataclass
class GateReport:
    desk_name: str
    gate1_skill: GateResult
    gate2_sign_preservation: GateResult
    gate3_hot_swap: GateResult

    @property
    def all_passed(self) -> bool:
        return (
            self.gate1_skill.passed
            and self.gate2_sign_preservation.passed
            and self.gate3_hot_swap.passed
        )


# ---------------------------------------------------------------------------
# Gate 1 — skill vs pre-registered naive baseline
# ---------------------------------------------------------------------------


def gate_skill_vs_baseline(
    desk_forecasts: list[Forecast],
    prints: list[Print],
    baseline_fn: Callable[[int, list[Print]], float],
    metric: str = "rmse",
) -> GateResult:
    """Compare desk RMSE (or MAE) against a pre-registered baseline_fn.

    baseline_fn(i, prints[:i]) returns the baseline's forecast value using
    only Prints strictly before index i (no look-ahead). The naive baseline
    is pre-registered per desk spec (§5.2 required section).

    Pairs each forecast with the next-in-order print by position; assumes
    caller has sorted both by time. For more complex matching, use the
    grading harness (grading/match.py) first and pass matched pairs here.
    """
    if len(desk_forecasts) != len(prints):
        return GateResult(
            name="skill_vs_baseline",
            passed=False,
            reason=(
                f"length mismatch: {len(desk_forecasts)} forecasts vs "
                f"{len(prints)} prints (caller should pre-match)"
            ),
        )
    if len(prints) < 2:
        return GateResult(
            name="skill_vs_baseline",
            passed=False,
            reason=f"need ≥2 (forecast, print) pairs; got {len(prints)}",
        )

    desk_errors: list[float] = []
    baseline_errors: list[float] = []
    for i, (f, p) in enumerate(zip(desk_forecasts, prints, strict=True)):
        baseline_value = baseline_fn(i, prints[:i])
        desk_errors.append(p.value - f.point_estimate)
        baseline_errors.append(p.value - baseline_value)

    desk_arr = np.array(desk_errors)
    base_arr = np.array(baseline_errors)
    if metric == "rmse":
        desk_metric = float(np.sqrt(np.mean(desk_arr**2)))
        base_metric = float(np.sqrt(np.mean(base_arr**2)))
    elif metric == "mae":
        desk_metric = float(np.mean(np.abs(desk_arr)))
        base_metric = float(np.mean(np.abs(base_arr)))
    else:
        return GateResult(
            name="skill_vs_baseline",
            passed=False,
            reason=f"unknown metric {metric!r}; use 'rmse' or 'mae'",
        )

    passed = desk_metric < base_metric
    return GateResult(
        name="skill_vs_baseline",
        passed=passed,
        metrics={
            "desk_metric": desk_metric,
            "baseline_metric": base_metric,
            "relative_improvement": (
                (base_metric - desk_metric) / base_metric if base_metric > 0 else 0.0
            ),
            "n": float(len(prints)),
        },
        reason=(
            f"{metric}: desk={desk_metric:.6f} vs baseline={base_metric:.6f}; "
            f"{'passed' if passed else 'failed'}"
        ),
    )


# ---------------------------------------------------------------------------
# Gate 2 — dev→test sign preservation (Kronos-RCA gate)
# ---------------------------------------------------------------------------


def gate_sign_preservation(
    dev_directional_scores: list[float],
    dev_forward_outcomes: list[float],
    test_directional_scores: list[float],
    test_forward_outcomes: list[float],
    expected_sign: str = "positive",
    dev_rho_floor: float = 0.20,
) -> GateResult:
    """Spearman correlation of desk's directional score against forward
    realised outcome. Sign must agree on dev and test per spec §7.1 Gate 2.

    Pre-registered directional claim (from desk spec) should match
    expected_sign ∈ {"positive", "negative"}. The default floor |dev_rho|
    ≥ 0.20 mirrors the dev-period bar in the Kronos V2 diagnostic.
    """
    if expected_sign not in ("positive", "negative"):
        return GateResult(
            name="sign_preservation",
            passed=False,
            reason=f"expected_sign must be 'positive' or 'negative'; got {expected_sign!r}",
        )
    if len(dev_directional_scores) < 10 or len(test_directional_scores) < 10:
        return GateResult(
            name="sign_preservation",
            passed=False,
            reason=(
                f"need ≥10 scored samples per split; got dev={len(dev_directional_scores)}, "
                f"test={len(test_directional_scores)}"
            ),
        )

    dev_rho, _dev_p = spearmanr(dev_directional_scores, dev_forward_outcomes)
    test_rho, _test_p = spearmanr(test_directional_scores, test_forward_outcomes)
    dev_rho = float(dev_rho)
    test_rho = float(test_rho)

    expected_dev_sign = 1.0 if expected_sign == "positive" else -1.0
    dev_aligned = np.sign(dev_rho) == expected_dev_sign and abs(dev_rho) >= dev_rho_floor
    test_sign_matches_dev = np.sign(test_rho) == np.sign(dev_rho) and test_rho != 0.0
    passed = bool(dev_aligned and test_sign_matches_dev)

    reason_parts: list[str] = [
        f"dev_rho={dev_rho:+.4f}",
        f"test_rho={test_rho:+.4f}",
        f"expected_sign={expected_sign}",
        f"dev_rho_floor={dev_rho_floor}",
    ]
    if not dev_aligned:
        reason_parts.append("dev_rho failed direction or magnitude floor")
    if not test_sign_matches_dev:
        reason_parts.append("test_rho sign disagrees with dev_rho (KRONOS-RCA PATTERN)")

    return GateResult(
        name="sign_preservation",
        passed=passed,
        metrics={
            "dev_rho": dev_rho,
            "test_rho": test_rho,
            "n_dev": float(len(dev_directional_scores)),
            "n_test": float(len(test_directional_scores)),
        },
        reason="; ".join(reason_parts),
    )


# ---------------------------------------------------------------------------
# Gate 3 — hot-swap against stub
# ---------------------------------------------------------------------------


def gate_hot_swap(
    run_controller_fn: Callable[[], bool],
    run_controller_with_stub_fn: Callable[[], bool],
) -> GateResult:
    """The real desk and a stub version of it must both let the Controller
    run to completion. The caller wires this up; this function just records
    both outcomes and emits a structured result.

    run_controller_fn and run_controller_with_stub_fn each return True iff
    the Controller ran to completion under that configuration. At spec v1.14
    the callables may also raise AssertionError (from in-closure
    post-exercise assertions about Decision validity, combined_signal delta,
    or contributing_ids membership). AssertionError is distinguished from
    generic runtime exceptions via the `failure_mode` field in metrics.

    metrics schema:
      - real_ok: 0.0 | 1.0 — whether the real-desk closure returned True.
      - stub_ok: 0.0 | 1.0 — whether the stub-swap closure returned True.
      - failure_mode: "passed" | "controller_exception" | "assertion_failure"
        — distinguishes integration bugs (controller raised) from harness
        contract violations (closure asserted on Decision properties).
    """
    # Try real-desk closure. AssertionError caught first (narrower exception)
    # before the generic Exception branch.
    try:
        real_ok = bool(run_controller_fn())
    except AssertionError as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={"real_ok": 0.0, "stub_ok": 0.0, "failure_mode": "assertion_failure"},
            reason=f"Real-desk closure assertion failed: {e!s}",
        )
    except Exception as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={"real_ok": 0.0, "stub_ok": 0.0, "failure_mode": "controller_exception"},
            reason=f"Controller raised with real desk: {e!r}",
        )

    # Try stub-swap closure.
    try:
        stub_ok = bool(run_controller_with_stub_fn())
    except AssertionError as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={
                "real_ok": 1.0 if real_ok else 0.0,
                "stub_ok": 0.0,
                "failure_mode": "assertion_failure",
            },
            reason=f"Stub-swap closure assertion failed: {e!s}",
        )
    except Exception as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={
                "real_ok": 1.0 if real_ok else 0.0,
                "stub_ok": 0.0,
                "failure_mode": "controller_exception",
            },
            reason=f"Controller raised after hot-swap to stub: {e!r}",
        )

    passed = real_ok and stub_ok
    return GateResult(
        name="hot_swap",
        passed=passed,
        metrics={
            "real_ok": 1.0 if real_ok else 0.0,
            "stub_ok": 1.0 if stub_ok else 0.0,
            "failure_mode": "passed" if passed else "controller_exception",
        },
        reason=(
            f"Controller run real={real_ok} stub={stub_ok}; "
            f"{'passed' if passed else 'failed — boundary has drifted'}"
        ),
    )
