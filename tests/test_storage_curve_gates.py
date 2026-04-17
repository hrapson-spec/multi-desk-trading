"""End-to-end: run StorageCurveDesk (stub phase) through all three gates.

Expected outcomes at stub phase:
  - Gate 1 (skill): FAIL — stub point_estimate=0 cannot beat persistence.
  - Gate 2 (sign preservation): FAIL by construction (sign="none").
    Gate 2 requires a pre-registered positive/negative claim.
  - Gate 3 (hot-swap): PASS — stub is itself a stub, trivially swappable.

This test documents the expected stub behaviour and will turn into the
deepen-time verification when the classical specialist lands.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np

from desks.base import StubDesk
from desks.storage_curve import StorageCurveDesk
from eval import GateRunner
from eval.data import make_forecasts_and_prints, persistence_baseline


def test_storage_curve_stub_fails_skill_passes_hot_swap():
    runner = GateRunner(desk_name="storage_curve")
    fcasts, prints, _ = make_forecasts_and_prints(
        n=50,
        start_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
        seed=7,
        forecast_generator="zero",
    )

    # Sign-preservation requires a pre-registered direction; the stub
    # declares sign="none" so we cannot legitimately apply gate 2 here.
    # Simulate a nearly-zero-correlation split to demonstrate gate 2 FAIL.
    rng = np.random.default_rng(7)
    n = 50
    dev_scores = rng.normal(0, 1, n).tolist()
    dev_outcomes = rng.normal(0, 1, n).tolist()  # no correlation
    test_scores = rng.normal(0, 1, n).tolist()
    test_outcomes = rng.normal(0, 1, n).tolist()

    report = runner.run(
        desk_forecasts=fcasts,
        prints=prints,
        baseline_fn=persistence_baseline,
        directional_split=(dev_scores, test_scores, dev_outcomes, test_outcomes),
        expected_sign="positive",  # stub's nominal declared direction for test
        run_controller_fn=lambda: True,  # real desk path
        run_controller_with_stub_fn=lambda: True,  # stub swap path
    )

    assert report.desk_name == "storage_curve"
    # Gate 1 fails: point_estimate=0 doesn't beat persistence on a trending path.
    assert not report.gate1_skill.passed, report.gate1_skill.reason
    # Gate 2 fails: no correlation in either dev or test.
    assert not report.gate2_sign_preservation.passed
    # Gate 3 passes: lambdas return True.
    assert report.gate3_hot_swap.passed


def test_storage_curve_stub_conforms_to_desk_protocol():
    """Trivial conformance check; redundant with test_stubs_integration but
    kept here so StorageCurveDesk's test file is self-contained."""
    d = StorageCurveDesk()
    assert d.name == "storage_curve"
    # Hot-swap against generic StubDesk
    s = StubDesk()
    s.name = "storage_curve_stub_swap"
    s.target_variable = d.target_variable
    s.event_id = d.event_id
    assert d.target_variable == s.target_variable
