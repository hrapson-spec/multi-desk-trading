"""Shapley attribution tests (spec §9.2).

Properties verified:
  - Efficiency: sum(Shapley values) = v(N) − v(∅) (= position_size when
    the decision is unclipped and v(∅) = 0 under no-desks coalition).
  - Symmetry: two desks with identical weights and forecasts get equal
    Shapley values.
  - Single-desk decision ⇒ the desk gets the full position_size.
  - Stale / null-signal desk ⇒ Shapley = 0 (contributes nothing to any
    coalition).
  - Window aggregation averages per-decision values and reports
    n_decisions correctly.
  - Cap: n > 6 raises (sampled variant is future work).
  - Persistence round-trip writes the row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from attribution import (
    SHAPLEY_EXACT_MAX_N,
    SHAPLEY_METRIC_POSITION_SIZE_DELTA,
    compute_shapley_signal_space,
    persist_shapley_rows,
)
from attribution.shapley import (
    _shapley_values_for_decision,
    _shapley_values_for_decision_sampled,
)
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence.db import connect, count_rows, init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.duckdb")
    init_db(c)
    yield c
    c.close()


def _prov(desk: str) -> Provenance:
    return Provenance(
        desk_name=desk,
        model_name="m",
        model_version="0.1",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def _fcast(desk: str, value: float, ts: datetime, *, stale: bool = False) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=ts,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=ts),
        point_estimate=value,
        uncertainty=UncertaintyInterval(level=0.8, lower=value - 5.0, upper=value + 5.0),
        directional_claim=DirectionalClaim(
            variable=WTI_FRONT_MONTH_CLOSE, sign="positive" if not stale else "none"
        ),
        staleness=stale,
        confidence=0.5 if stale else 1.0,
        provenance=_prov(desk),
    )


def _regime(now: datetime) -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=now,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def _make_weights(desks: list[str], w: float) -> list[dict]:
    return [{"desk_name": d, "target_variable": WTI_FRONT_MONTH_CLOSE, "weight": w} for d in desks]


# ---------------------------------------------------------------------------
# Property tests on the inner _shapley_values_for_decision
# ---------------------------------------------------------------------------


def test_shapley_efficiency_two_desks_unclipped():
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["a", "b"], 0.5)
    recent = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 80.0, now),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 100.0, now),
    }
    values = _shapley_values_for_decision(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,  # no clip
    )
    # v(N) = 0.5*80 + 0.5*100 = 90; v(∅) = 0 → sum(values) should equal 90.
    assert sum(values.values()) == pytest.approx(90.0)
    # Asymmetric forecasts ⇒ asymmetric Shapley contributions.
    assert values["a"] == pytest.approx(40.0)
    assert values["b"] == pytest.approx(50.0)


def test_shapley_symmetry_identical_inputs_identical_values():
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["a", "b", "c"], 1.0 / 3.0)
    recent = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 90.0, now),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 90.0, now),
        ("c", WTI_FRONT_MONTH_CLOSE): _fcast("c", 90.0, now),
    }
    values = _shapley_values_for_decision(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
    )
    assert values["a"] == pytest.approx(values["b"])
    assert values["b"] == pytest.approx(values["c"])
    assert sum(values.values()) == pytest.approx(90.0)


def test_shapley_stale_desk_gets_zero():
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["a", "b"], 0.5)
    recent = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 80.0, now),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 1e6, now, stale=True),
    }
    values = _shapley_values_for_decision(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
    )
    assert values["b"] == pytest.approx(0.0)
    # a alone generates the full 0.5*80 = 40 position.
    assert values["a"] == pytest.approx(40.0)


def test_shapley_single_desk_gets_full_position():
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["solo"], 1.0)
    recent = {("solo", WTI_FRONT_MONTH_CLOSE): _fcast("solo", 73.0, now)}
    values = _shapley_values_for_decision(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
    )
    assert values["solo"] == pytest.approx(73.0)


def test_shapley_rejects_over_cap():
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    n = SHAPLEY_EXACT_MAX_N + 1
    desk_names = [f"d{i}" for i in range(n)]
    weights = _make_weights(desk_names, 1.0 / n)
    recent = {(d, WTI_FRONT_MONTH_CLOSE): _fcast(d, 80.0, now) for d in desk_names}
    with pytest.raises(ValueError, match="capped at n=6"):
        _shapley_values_for_decision(
            weights=weights,
            recent_forecasts=recent,
            k_regime=1.0,
            pos_limit_regime=1000.0,
        )


# ---------------------------------------------------------------------------
# Windowed aggregation via compute_shapley_signal_space
# ---------------------------------------------------------------------------


def test_shapley_window_aggregation_two_decisions(conn):
    """Two decisions with identical desks; second decision doubles the
    forecast magnitudes; expect per-desk Shapley average between the
    per-decision values and n_decisions=2."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 4, 16, 11, 0, 0, tzinfo=UTC)
    review = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("a", WTI_FRONT_MONTH_CLOSE),
            ("b", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)

    recent1 = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 80.0, t1),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 100.0, t1),
    }
    d1 = ctrl.decide(now_utc=t1, regime_label=_regime(t1), recent_forecasts=recent1)

    recent2 = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 160.0, t2),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 200.0, t2),
    }
    d2 = ctrl.decide(now_utc=t2, regime_label=_regime(t2), recent_forecasts=recent2)

    rows = compute_shapley_signal_space(
        conn=conn,
        decisions=[d1, d2],
        recent_forecasts_by_decision={d1.decision_id: recent1, d2.decision_id: recent2},
        review_ts_utc=review,
    )
    assert len(rows) == 2
    by_desk = {r.desk_name: r for r in rows}
    # Per-decision Shapley:
    # d1: a=40, b=50 (sum 90) — 0.5*80 + 0.5*100
    # d2: a=80, b=100 (sum 180) — 0.5*160 + 0.5*200
    # Average: a = (40+80)/2 = 60, b = (50+100)/2 = 75
    assert by_desk["a"].shapley_value == pytest.approx(60.0)
    assert by_desk["b"].shapley_value == pytest.approx(75.0)
    assert by_desk["a"].n_decisions == 2
    assert by_desk["b"].n_decisions == 2
    assert all(r.metric_name == SHAPLEY_METRIC_POSITION_SIZE_DELTA for r in rows)
    assert all(r.coalitions_mode == "exact" for r in rows)


def test_shapley_persists_to_duckdb(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    review = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("a", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    recent = {("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 50.0, now)}
    d = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    rows = compute_shapley_signal_space(
        conn=conn,
        decisions=[d],
        recent_forecasts_by_decision={d.decision_id: recent},
        review_ts_utc=review,
    )
    persist_shapley_rows(conn, rows)
    assert count_rows(conn, "attribution_shapley") == 1


def test_shapley_empty_window_is_empty_output(conn):
    review = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    rows = compute_shapley_signal_space(
        conn=conn,
        decisions=[],
        recent_forecasts_by_decision={},
        review_ts_utc=review,
    )
    assert rows == []


# ---------------------------------------------------------------------------
# Sampled Shapley (§9.2 sampled path for n > 6)
# ---------------------------------------------------------------------------


def test_sampled_shapley_converges_to_exact_for_small_n():
    """For n ≤ 6, sampled Shapley with ≥ 500 samples should land close
    to the exact value. Uses a fixed seed for determinism."""
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["a", "b", "c"], 1.0 / 3.0)
    recent = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 100.0, now),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 50.0, now),
        ("c", WTI_FRONT_MONTH_CLOSE): _fcast("c", 30.0, now),
    }
    exact = _shapley_values_for_decision(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
    )
    sampled = _shapley_values_for_decision_sampled(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
        n_samples=2000,
        seed=1234,
    )
    # Expected Shapley values for uniform weights + asymmetric forecasts:
    # v(S) = sum of 1/3 * point_estimate over S. For each desk, marginal
    # is always exactly 1/3 * point_estimate → Shapley = point_estimate/3.
    assert exact["a"] == pytest.approx(100.0 / 3.0)
    assert exact["b"] == pytest.approx(50.0 / 3.0)
    assert exact["c"] == pytest.approx(30.0 / 3.0)
    # Sampled with 2000 samples should converge very tightly (deterministic
    # path here — marginal contributions don't depend on order).
    assert sampled["a"] == pytest.approx(exact["a"], abs=1e-9)
    assert sampled["b"] == pytest.approx(exact["b"], abs=1e-9)
    assert sampled["c"] == pytest.approx(exact["c"], abs=1e-9)


def test_sampled_shapley_replay_deterministic_under_seed():
    """Same seed ⇒ byte-identical sampled values (spec §3.1)."""
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["a", "b", "c", "d"], 0.25)
    recent = {
        (d, WTI_FRONT_MONTH_CLOSE): _fcast(d, 80.0 + i * 10, now)
        for i, d in enumerate(["a", "b", "c", "d"])
    }
    s1 = _shapley_values_for_decision_sampled(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
        n_samples=100,
        seed=42,
    )
    s2 = _shapley_values_for_decision_sampled(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=1000.0,
        n_samples=100,
        seed=42,
    )
    assert s1 == s2


def test_sampled_shapley_unbiased_over_clipped_decision():
    """With clip binding, exact Shapley values can be small / discrete.
    Sampled estimator should converge to exact in expectation."""
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    weights = _make_weights(["a", "b", "c"], 1.0 / 3.0)
    recent = {(d, WTI_FRONT_MONTH_CLOSE): _fcast(d, 300.0, now) for d in ["a", "b", "c"]}
    exact = _shapley_values_for_decision(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=50.0,  # binding
    )
    sampled = _shapley_values_for_decision_sampled(
        weights=weights,
        recent_forecasts=recent,
        k_regime=1.0,
        pos_limit_regime=50.0,
        n_samples=3000,
        seed=7,
    )
    for d in ["a", "b", "c"]:
        # Tolerance of 2% of the clip; 3000 samples is tight but variance
        # in clip-binding coalitions is real.
        assert sampled[d] == pytest.approx(exact[d], abs=1.0)


def test_auto_mode_uses_sampled_for_large_n(conn):
    """compute_shapley_signal_space(mode="auto") switches to sampled
    when n > SHAPLEY_EXACT_MAX_N. coalitions_mode reflects the switch."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    t = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    review = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    n = SHAPLEY_EXACT_MAX_N + 1
    desk_names = [f"d{i}" for i in range(n)]
    seed_cold_start(
        conn,
        desks=[(name, WTI_FRONT_MONTH_CLOSE) for name in desk_names],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=10_000.0,
    )
    ctrl = Controller(conn=conn)
    recent = {
        (name, WTI_FRONT_MONTH_CLOSE): _fcast(name, 80.0 + i, t)
        for i, name in enumerate(desk_names)
    }
    d = ctrl.decide(now_utc=t, regime_label=_regime(t), recent_forecasts=recent)
    rows = compute_shapley_signal_space(
        conn=conn,
        decisions=[d],
        recent_forecasts_by_decision={d.decision_id: recent},
        review_ts_utc=review,
        mode="auto",
        n_samples=200,
        seed=1,
    )
    assert all(r.coalitions_mode == "sampled" for r in rows)
    # Sum should still approximately equal v(N) − v(∅) = combined_signal.
    assert sum(r.shapley_value for r in rows) == pytest.approx(d.combined_signal, rel=0.05)


def test_compute_shapley_rejects_invalid_mode(conn):
    review = datetime(2026, 4, 23, 0, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="exact/sampled/auto"):
        compute_shapley_signal_space(
            conn=conn,
            decisions=[],
            recent_forecasts_by_decision={},
            review_ts_utc=review,
            mode="bogus",
        )
