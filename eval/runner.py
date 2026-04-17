"""GateRunner: compose the three hard gates into a per-desk evaluation.

Typical usage (per desk spec §5.2 gate-pass plan):

    runner = GateRunner(desk_name="storage_curve")
    report = runner.run(
        desk_forecasts=dev_forecasts + test_forecasts,
        prints=dev_prints + test_prints,
        baseline_fn=persistence_baseline,
        directional_split=(dev_directional, test_directional,
                           dev_outcomes, test_outcomes),
        expected_sign="positive",
        run_controller_fn=lambda: run_controller(real_desk),
        run_controller_with_stub_fn=lambda: run_controller(StubDesk()),
    )
    assert report.all_passed
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from contracts.v1 import Forecast, Print

from .gates import (
    GateReport,
    gate_hot_swap,
    gate_sign_preservation,
    gate_skill_vs_baseline,
)


@dataclass
class GateRunner:
    desk_name: str
    skill_metric: str = "rmse"
    dev_rho_floor: float = 0.20

    def run(
        self,
        *,
        desk_forecasts: list[Forecast],
        prints: list[Print],
        baseline_fn: Callable[[int, list[Print]], float],
        directional_split: tuple[list[float], list[float], list[float], list[float]],
        expected_sign: str,
        run_controller_fn: Callable[[], bool],
        run_controller_with_stub_fn: Callable[[], bool],
    ) -> GateReport:
        dev_scores, test_scores, dev_outcomes, test_outcomes = directional_split
        gate1 = gate_skill_vs_baseline(
            desk_forecasts=desk_forecasts,
            prints=prints,
            baseline_fn=baseline_fn,
            metric=self.skill_metric,
        )
        gate2 = gate_sign_preservation(
            dev_directional_scores=dev_scores,
            dev_forward_outcomes=dev_outcomes,
            test_directional_scores=test_scores,
            test_forward_outcomes=test_outcomes,
            expected_sign=expected_sign,
            dev_rho_floor=self.dev_rho_floor,
        )
        gate3 = gate_hot_swap(
            run_controller_fn=run_controller_fn,
            run_controller_with_stub_fn=run_controller_with_stub_fn,
        )
        return GateReport(
            desk_name=self.desk_name,
            gate1_skill=gate1,
            gate2_sign_preservation=gate2,
            gate3_hot_swap=gate3,
        )
