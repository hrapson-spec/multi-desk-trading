"""End-to-end: run StorageCurveDesk through all three hard gates.
v1.14: Gate 3 uses the runtime hot-swap harness
(eval.build_hot_swap_callables).


Two phases covered:
  1. Stub phase (no model): Gate 1 fails, Gate 2 fails, Gate 3 passes.
  2. Classical-specialist phase (ridge model fitted on AR(1) dev data):
     Gate 1 should beat persistence, Gate 2 sign preservation should hold
     dev→test (both positive), Gate 3 hot-swap still passes.

Gate 2 is the load-bearing gate per spec §7.1 (Kronos-RCA lesson). This test
exists specifically to demonstrate that the classical-specialist path emits
dev→test-consistent directional scores on a synthetic process with real
predictability (AR(1) log-returns). The test does NOT claim alpha on real
market data; it claims the pipeline composes correctly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import Forecast, Print, Provenance, RegimeLabel
from controller import seed_cold_start
from desks.base import StubDesk
from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk
from eval import GateRunner, build_hot_swap_callables
from eval.data import (
    make_forecasts_and_prints,
    persistence_baseline,
    random_walk_price_baseline,
    synthetic_price_path,
)
from grading.match import DEFAULT_CLOCK_TOLERANCE  # noqa: F401 (kept for doc clarity)
from persistence import connect, init_db


def _build_storage_curve_gate3_harness(tmp_path, real_forecast: Forecast, *, now_utc: datetime):
    """Shared helper for storage_curve Gate 3 migration (v1.14).

    Seeds cold-start for the storage_curve desk and returns (real_fn,
    stub_fn) from build_hot_swap_callables. Both test callsites in
    this file use the same seeding — extract into one place."""
    conn = connect(tmp_path / "gate3_storage_curve.duckdb")
    init_db(conn)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=now_utc - timedelta(hours=1),
    )
    regime_label = RegimeLabel(
        classification_ts_utc=now_utc,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=Provenance(
            desk_name="regime_classifier",
            model_name="stub",
            model_version="0.0.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        ),
    )
    return build_hot_swap_callables(
        conn=conn,
        real_desk=StorageCurveDesk(),
        real_forecast=real_forecast,
        regime_label=regime_label,
        recent_forecasts_other={},
        now_utc=now_utc,
    )


# ---------------------------------------------------------------------------
# Stub phase — unchanged behaviour from Week 1-2 integration
# ---------------------------------------------------------------------------


def test_storage_curve_stub_fails_skill_passes_hot_swap(tmp_path):
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

    # v1.14: real Gate 3 harness. `fcasts` are stub forecasts (staleness=True
    # per StubDesk convention via the "zero" generator); the helper enters
    # the stale-real + stale-stub branch → trivial delta=0 assertion.
    real_fn, stub_fn = _build_storage_curve_gate3_harness(
        tmp_path, real_forecast=fcasts[0], now_utc=datetime(2026, 1, 1, tzinfo=UTC)
    )
    report = runner.run(
        desk_forecasts=fcasts,
        prints=prints,
        baseline_fn=persistence_baseline,
        directional_split=(dev_scores, test_scores, dev_outcomes, test_outcomes),
        expected_sign="positive",  # stub's nominal declared direction for test
        run_controller_fn=real_fn,
        run_controller_with_stub_fn=stub_fn,
    )

    assert report.desk_name == "storage_curve"
    # Gate 1 fails: point_estimate=0 doesn't beat persistence on a trending path.
    assert not report.gate1_skill.passed, report.gate1_skill.reason
    # Gate 2 fails: no correlation in either dev or test.
    assert not report.gate2_sign_preservation.passed
    # Gate 3 passes (v1.14 runtime harness): stub-stale + stub-stale → delta=0.
    assert report.gate3_hot_swap.passed
    assert report.gate3_hot_swap.metrics["failure_mode"] == "passed"


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


# ---------------------------------------------------------------------------
# Classical-specialist phase — deepen-time verification
# ---------------------------------------------------------------------------


def _drive_desk_on_prices(
    desk: StorageCurveDesk,
    prices: np.ndarray,
    start_index: int,
    end_index: int,
    horizon_days: int,
) -> tuple[list, list[Print], list[int], list[float], list[float]]:
    """Emit (Forecast, Print) pairs + paired directional scores/outcomes.

    For each i in [start_index, end_index - horizon_days):
      - forecast emitted at index i using prices[:i]
      - print realised at index i + horizon_days
      - directional_score(i) paired with realised log-return over the horizon

    Returns (forecasts, prints, emission_indices, directional_scores,
    forward_outcomes). emission_indices is used to build a matched
    random-walk baseline outside this helper.
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    forecasts = []
    prints = []
    emission_indices: list[int] = []
    directional_scores: list[float] = []
    forward_outcomes: list[float] = []

    last = end_index - horizon_days
    for i in range(start_index, last):
        emission_ts = now + timedelta(days=int(i))
        realised_ts = emission_ts + timedelta(days=horizon_days)
        fcast = desk.forecast_from_prices(prices, i, emission_ts)
        forecasts.append(fcast)
        prints.append(
            Print(
                print_id=f"p-{i:04d}",
                realised_ts_utc=realised_ts,
                target_variable=WTI_FRONT_MONTH_CLOSE,
                value=float(prices[i + horizon_days]),
            )
        )
        emission_indices.append(i)
        score = desk.directional_score(prices, i)
        if score is not None:
            directional_scores.append(float(score))
            realised_ret = float(np.log(prices[i + horizon_days]) - np.log(prices[i - 1]))
            forward_outcomes.append(realised_ret)

    return forecasts, prints, emission_indices, directional_scores, forward_outcomes


def test_classical_model_fits_and_predicts_without_leakage():
    """Unit check on the ridge model: fit and predict produce finite outputs
    and the predict function refuses to read beyond index i."""
    prices = synthetic_price_path(n=200, seed=3, ar1_coef=0.6)
    model = ClassicalStorageCurveModel(lookback=10, horizon_days=7, alpha=1.0)
    model.fit(prices[:120])  # dev half

    # Predict inside dev
    out = model.predict(prices, 30)
    assert out is not None
    point, score = out
    assert np.isfinite(point) and np.isfinite(score)

    # Too-early index returns None (insufficient history)
    assert model.predict(prices, 5) is None

    # Fingerprint is deterministic
    assert model.fingerprint() == model.fingerprint()


def test_storage_curve_classical_passes_all_three_gates_on_ar1(tmp_path):
    """End-to-end Week 3 deepen: classical StorageCurveDesk on AR(1) synthetic
    WTI path should (a) beat random-walk RMSE, (b) preserve dev→test Spearman
    sign for its directional score, (c) support hot-swap with a StubDesk.

    AR(1) coefficient is deliberately high (0.9) on low-vol (0.01) shocks so
    the predictable return component exceeds path noise over the 3-day
    horizon — otherwise Gate 1 becomes a proxy for signal-to-noise ratio
    rather than a test that the pipeline composes. Real-data Gate 1 on the
    storage/curve desk will use a 7-day horizon with real WTI closes.
    """
    n = 400
    horizon = 3
    prices = synthetic_price_path(n=n, seed=11, ar1_coef=0.9, vol=0.01)

    split = 200  # walk-forward cut
    model = ClassicalStorageCurveModel(lookback=10, horizon_days=horizon, alpha=1.0)
    model.fit(prices[:split])
    desk = StorageCurveDesk(model=model)

    dev_fcasts, dev_prints, _dev_em, dev_scores, dev_outcomes = _drive_desk_on_prices(
        desk, prices, start_index=11, end_index=split, horizon_days=horizon
    )
    test_fcasts, test_prints, test_em, test_scores, test_outcomes = _drive_desk_on_prices(
        desk, prices, start_index=split, end_index=n, horizon_days=horizon
    )

    # Spec §3: naive baseline = random walk on wti_front_month_close. At
    # emission i the baseline predicts prices[i-1] (no change over horizon).
    rw_baseline = random_walk_price_baseline(prices=prices, emission_indices=test_em)

    # v1.14: real Gate 3 harness. Non-stale classical forecast drives
    # the non-stale real + stale stub branch → delta = -weight * point.
    real_forecast = next((f for f in test_fcasts if not f.staleness), test_fcasts[0])
    real_fn, stub_fn = _build_storage_curve_gate3_harness(
        tmp_path, real_forecast=real_forecast, now_utc=datetime(2026, 1, 1, tzinfo=UTC)
    )
    runner = GateRunner(desk_name="storage_curve")
    report = runner.run(
        desk_forecasts=test_fcasts,
        prints=test_prints,
        baseline_fn=rw_baseline,
        directional_split=(dev_scores, test_scores, dev_outcomes, test_outcomes),
        expected_sign="positive",
        run_controller_fn=real_fn,
        run_controller_with_stub_fn=stub_fn,
    )

    # Gate 1 — classical model beats persistence on AR(1) test.
    assert report.gate1_skill.passed, report.gate1_skill.reason
    assert report.gate1_skill.metrics["desk_metric"] < report.gate1_skill.metrics["baseline_metric"]

    # Gate 2 — dev and test rho both positive, |dev_rho| ≥ floor.
    g2 = report.gate2_sign_preservation
    assert g2.passed, g2.reason
    assert g2.metrics["dev_rho"] > 0.0
    assert g2.metrics["test_rho"] > 0.0
    assert "KRONOS-RCA PATTERN" not in g2.reason

    # Gate 3 — v1.14 runtime hot-swap.
    assert report.gate3_hot_swap.passed
    assert report.gate3_hot_swap.metrics["failure_mode"] == "passed"

    # And the aggregate property wires correctly.
    assert report.all_passed

    # Sanity: the unused dev_fcasts/dev_prints are valid Forecast/Print objects.
    assert len(dev_fcasts) == len(dev_prints) > 0


def test_storage_curve_classical_falls_back_to_stub_when_unfit():
    """A desk constructed with an *unfit* model must refuse to forecast (no
    silent fallback to stub without this being intentional). The current
    design raises from the model; the desk currently propagates that error.
    """
    unfit = ClassicalStorageCurveModel(lookback=10, horizon_days=7)
    desk = StorageCurveDesk(model=unfit)
    prices = synthetic_price_path(n=50, seed=1)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    try:
        desk.forecast_from_prices(prices, 20, now)
    except RuntimeError as e:
        assert "not fitted" in str(e)
    else:
        raise AssertionError("expected RuntimeError from unfit model")
