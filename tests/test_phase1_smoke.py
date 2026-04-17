"""Phase 1 end-to-end smoke test.

Exercises every major subsystem in one pass, using the bus as the
transport layer:

  1. Persistence + Bus + cold-start seeding (§14.8).
  2. StorageCurveDesk (classical specialist) emits a Forecast;
     four stubs emit null-signal Forecasts alongside.
  3. StubClassifier emits a RegimeLabel (regime_boot).
  4. Controller reads the latest regime + weights + params + recent
     forecasts and emits a Decision via the bus.
  5. LODO attribution runs, bus-publishes one AttributionLodo row per
     desk that was in the weight matrix.
  6. Print arrives; grading harness matches it to the StorageCurveDesk
     forecast; Grade is emitted via the bus.
  7. Assert final DuckDB state: one row in each relevant table, counts
     reflect the run, and the LODO delta for the classical desk has
     the expected sign.

Not a skill test. Not an alpha claim. Exists to show the wiring
composes so that the research loop has a full event trail to consume.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from attribution import compute_lodo_signal_space
from bus.bus import Bus
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Print,
    Provenance,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from desks.base import StubClassifier, StubDesk
from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk
from eval.data import synthetic_price_path
from grading.match import grade
from persistence.db import connect, count_rows, init_db


@pytest.fixture
def smoke_db(tmp_path):
    c = connect(tmp_path / "smoke.duckdb")
    init_db(c)
    yield c
    c.close()


def _fit_storage_curve() -> tuple[StorageCurveDesk, np.ndarray]:
    prices = synthetic_price_path(n=400, seed=11, ar1_coef=0.9, vol=0.01)
    model = ClassicalStorageCurveModel(lookback=10, horizon_days=3, alpha=1.0)
    model.fit(prices[:200])
    return StorageCurveDesk(model=model), prices


def test_phase1_end_to_end_smoke(smoke_db):
    bus = Bus(conn=smoke_db, mode="development")
    boot_ts = datetime(2026, 4, 16, 9, 0, 0, 123456, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    realised = datetime(2026, 4, 19, 10, 0, 0, tzinfo=UTC)  # 3-day horizon

    # --- 1. Cold-start for 5 desks (1 real + 4 stubs) ---------------------
    all_desks = [
        ("storage_curve", WTI_FRONT_MONTH_CLOSE),
        ("supply", WTI_FRONT_MONTH_CLOSE),
        ("demand", WTI_FRONT_MONTH_CLOSE),
        ("geopolitics", WTI_FRONT_MONTH_CLOSE),
        ("macro", WTI_FRONT_MONTH_CLOSE),
    ]
    weights, params = seed_cold_start(
        smoke_db,
        desks=all_desks,
        regime_ids=["regime_boot"],
        boot_ts=boot_ts,
        default_cold_start_limit=200.0,  # generous so clip isn't binding
    )
    assert count_rows(smoke_db, "signal_weights") == 5
    assert count_rows(smoke_db, "controller_params") == 1

    # --- 2. Desks emit forecasts via the bus -------------------------------
    sc_desk, prices = _fit_storage_curve()
    sc_fcast = sc_desk.forecast_from_prices(prices=prices, i=250, now_utc=now)
    # Override horizon for this smoke run so Print matching is deterministic
    sc_fcast = sc_fcast.model_copy(
        update={"horizon": EventHorizon(event_id="cftc_cot", expected_ts_utc=realised)}
    )
    bus.publish_forecast(sc_fcast)

    # Stubs emit null-signal forecasts
    stub_fcasts: list[Forecast] = []
    for desk_name in ["supply", "demand", "geopolitics", "macro"]:
        s = StubDesk()
        s.name = desk_name
        s.target_variable = WTI_FRONT_MONTH_CLOSE
        s.event_id = "cftc_cot"
        s.horizon_days = 3
        f = s._build_stub_forecast(now)
        stub_fcasts.append(f)
        bus.publish_forecast(f)

    assert count_rows(smoke_db, "forecasts") == 5

    # --- 3. StubClassifier emits a RegimeLabel -----------------------------
    classifier = StubClassifier()
    (regime_label,) = classifier.on_schedule_fire(
        now_utc=now, recent_forecasts=[sc_fcast, *stub_fcasts]
    )
    bus.publish_regime_label(regime_label)
    assert count_rows(smoke_db, "regime_labels") == 1

    # --- 4. Controller decides --------------------------------------------
    ctrl = Controller(conn=smoke_db)
    recent = {(sc_fcast.provenance.desk_name, sc_fcast.target_variable): sc_fcast}
    for f in stub_fcasts:
        recent[(f.provenance.desk_name, f.target_variable)] = f

    decision = ctrl.decide(now_utc=now, regime_label=regime_label, recent_forecasts=recent)
    bus.publish_decision(decision)
    assert count_rows(smoke_db, "decisions") == 1

    # Only StorageCurveDesk is non-stale; combined_signal comes from it alone.
    assert len(decision.input_forecast_ids) == 1
    assert decision.input_forecast_ids[0] == sc_fcast.forecast_id
    # 0.2 * sc_fcast.point_estimate (uniform weight across 5 desks); unclipped
    expected_combined = 0.2 * sc_fcast.point_estimate
    assert decision.combined_signal == pytest.approx(expected_combined)

    # --- 5. LODO runs; one AttributionLodo per desk in weight row ----------
    lodo_rows = compute_lodo_signal_space(
        conn=smoke_db,
        decision=decision,
        recent_forecasts=recent,
        computed_ts_utc=now,
    )
    for a in lodo_rows:
        bus.publish_attribution_lodo(a)
    assert count_rows(smoke_db, "attribution_lodo") == 5

    # storage_curve is the only non-stale contributor → its LODO removes the
    # entire position; the four stubs never contributed → their deltas are 0.
    by_desk = {a.desk_name: a.contribution_metric for a in lodo_rows}
    assert by_desk["storage_curve"] == pytest.approx(decision.position_size)
    for stub_name in ["supply", "demand", "geopolitics", "macro"]:
        assert by_desk[stub_name] == pytest.approx(0.0)

    # --- 6. Print arrives; grading harness grades the StorageCurveDesk ----
    realised_value = float(prices[253])  # i=250 + horizon=3
    print_event = Print(
        print_id=str(uuid.uuid4()),
        realised_ts_utc=realised,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        value=realised_value,
        event_id="cftc_cot",
    )
    bus.publish_print(print_event)
    assert count_rows(smoke_db, "prints") == 1

    g = grade(forecast=sc_fcast, p=print_event, grading_ts_utc=realised)
    assert g is not None
    bus.publish_grade(g)
    assert count_rows(smoke_db, "grades") == 1

    # schedule_slip_seconds is 0 because Forecast.expected_ts_utc == realised.
    assert g.schedule_slip_seconds == 0.0

    # --- 7. Final shape: every event tier has at least one row ------------
    # Forecasts (5), Prints (1), Grades (1), Decisions (1),
    # SignalWeights (5), ControllerParams (1), RegimeLabels (1),
    # AttributionLodo (5), AttributionShapley (0) — Shapley is a later commit.
    assert count_rows(smoke_db, "forecasts") == 5
    assert count_rows(smoke_db, "prints") == 1
    assert count_rows(smoke_db, "grades") == 1
    assert count_rows(smoke_db, "decisions") == 1
    assert count_rows(smoke_db, "signal_weights") == 5
    assert count_rows(smoke_db, "controller_params") == 1
    assert count_rows(smoke_db, "regime_labels") == 1
    assert count_rows(smoke_db, "attribution_lodo") == 5
    assert count_rows(smoke_db, "attribution_shapley") == 0


def test_phase1_smoke_bus_rejects_dirty_tree_in_production(smoke_db):
    """Regression: production-mode bus rejects Forecasts whose provenance
    carries a `-dirty` code_commit suffix (spec §4.3 + §11 invariant)."""
    bus = Bus(conn=smoke_db, mode="production")
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    dirty_prov = Provenance(
        desk_name="storage_curve",
        model_name="m",
        model_version="0.1",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="deadbeefcafe-dirty",
    )
    f = Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=now,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=now + timedelta(days=3)),
        point_estimate=82.0,
        uncertainty=UncertaintyInterval(level=0.8, lower=75.0, upper=90.0),
        directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
        staleness=False,
        confidence=0.7,
        provenance=dirty_prov,
    )
    from bus.bus import BusValidationError

    with pytest.raises(BusValidationError) as excinfo:
        bus.publish_forecast(f)
    assert excinfo.value.reason == "dirty_tree_rejected"
    # And nothing was written.
    assert count_rows(smoke_db, "forecasts") == 0
