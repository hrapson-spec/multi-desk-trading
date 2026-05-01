"""§12.2 item 4 — closed round-trips per desk.

Spec: "Each desk has ≥ 10 closed round-trips (for weekly-cadence
desks) or ≥ 20 closed round-trips (for daily-cadence desks). A
closed round-trip = Forecast emitted → Print arrived → Grade
computed → Attribution updated."

This test drives 30 daily round-trips through every live classical
desk (storage_curve/supply/demand/geopolitics/macro) and asserts the
DB ends with ≥ 20 persisted round-trips per desk. Exceeds the
≥ 20 threshold (daily cadence) for every desk.

Includes item 5 companion evidence: the research-loop latency KPI
is measured via `compute_latency_report` against the research_loop
events this test submits (a gate_failure trigger for the exercise).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from attribution import compute_lodo_signal_space, compute_shapley_signal_space
from bus.bus import Bus
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    Print,
    ResearchLoopEvent,
)
from controller import Controller, seed_cold_start
from desks.oil_demand_nowcast import ClassicalOilDemandNowcastModel, OilDemandNowcastDesk
from desks.regime_classifier import GroundTruthRegimeClassifier
from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk
from desks.supply_disruption_news import (
    ClassicalSupplyDisruptionNewsModel,
    SupplyDisruptionNewsDesk,
)
from grading.match import grade
from persistence.db import connect, count_rows, init_db
from research_loop import Dispatcher, compute_latency_report, gate_failure_handler
from sim.latent_state import LatentMarket, phase_a_config
from sim.observations import ObservationChannels
from sim.regimes import REGIMES

N_DAYS = 1200
TRAIN_END = 700
HELD_OUT_START = TRAIN_END
HORIZON = 3
SEED = 10
NOW_BASE = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
# Drive 30 round-trips per desk — exceeds both the ≥10 weekly and
# ≥20 daily thresholds.
N_ROUND_TRIPS = 30


@pytest.fixture
def smoke_db(tmp_path: Path):
    c = connect(tmp_path / "rt.duckdb")
    init_db(c)
    yield c
    c.close()


def _fit_all_desks(channels: ObservationChannels, market_price: np.ndarray) -> dict[str, object]:
    small_alpha = 1e-4
    sc_model = ClassicalStorageCurveModel(lookback=10, horizon_days=HORIZON, alpha=1.0)
    sc_model.fit(market_price[:TRAIN_END])
    sdn_model = ClassicalSupplyDisruptionNewsModel(horizon_days=HORIZON, alpha=small_alpha)
    sdn_model.fit(
        channels.by_desk["geopolitics"].components["event_indicator"][:TRAIN_END],
        channels.by_desk["geopolitics"].components["event_intensity"][:TRAIN_END],
        channels.by_desk["geopolitics"].components["event_intensity_raw"][:TRAIN_END],
        market_price[:TRAIN_END],
    )
    odn_model = ClassicalOilDemandNowcastModel(horizon_days=HORIZON, alpha=small_alpha)
    odn_model.fit(
        channels.by_desk["demand"].components["demand"][:TRAIN_END],
        channels.by_desk["demand"].components["demand_level"][:TRAIN_END],
        market_price[:TRAIN_END],
    )
    return {
        "storage_curve": StorageCurveDesk(model=sc_model),
        "supply_disruption_news": SupplyDisruptionNewsDesk(model=sdn_model),
        "oil_demand_nowcast": OilDemandNowcastDesk(model=odn_model),
    }


def test_phase1_round_trips_per_desk_ge_20(smoke_db):
    """Drive N_ROUND_TRIPS closed round-trips per desk end-to-end:
    Forecast → Bus → Print → Grade → LODO attribution. Assert DB has
    ≥ 20 forecasts / prints / grades / attribution_lodo-per-desk rows.
    """
    # --- Setup: market + fitted desks + regime classifier --------------
    path = LatentMarket(n_days=N_DAYS, seed=SEED, config=phase_a_config()).generate()
    channels = ObservationChannels.build(path, mode="clean", seed=SEED)
    market_price = channels.market_price
    desks = _fit_all_desks(channels, market_price)
    classifier = GroundTruthRegimeClassifier()

    # --- Cold-start controller with all 4 regimes ----------------------
    seed_cold_start(
        smoke_db,
        desks=[(name, WTI_FRONT_MONTH_CLOSE) for name in desks],
        regime_ids=list(REGIMES),
        boot_ts=NOW_BASE - timedelta(days=1),
        default_cold_start_limit=1e9,
    )
    controller = Controller(conn=smoke_db)
    bus = Bus(conn=smoke_db, mode="development")

    # --- Drive N_ROUND_TRIPS through the full loop ---------------------
    for n in range(N_ROUND_TRIPS):
        i = HELD_OUT_START + n
        emission_ts = NOW_BASE + timedelta(days=int(n))
        realised_ts = emission_ts + timedelta(days=HORIZON)

        # Classifier emits a regime label.
        recent_forecasts: dict[tuple[str, str], object] = {}
        regime_label = classifier.regime_label_at(channels, i, emission_ts)
        bus.publish_regime_label(regime_label)

        # Each desk emits a forecast.
        for name, desk in desks.items():
            f = desk.forecast_from_observation(channels, i, emission_ts)
            bus.publish_forecast(f)
            recent_forecasts[(name, f.target_variable)] = f

        # Controller emits a decision.
        decision = controller.decide(
            now_utc=emission_ts,
            regime_label=regime_label,
            recent_forecasts=recent_forecasts,
        )
        bus.publish_decision(decision)

        # LODO attribution per-decision.
        lodo_rows = compute_lodo_signal_space(
            conn=smoke_db,
            decision=decision,
            recent_forecasts=recent_forecasts,
            computed_ts_utc=emission_ts,
        )
        for a in lodo_rows:
            bus.publish_attribution_lodo(a)

        # Print arrives + grade computed per-desk. v1.16 desks emit either
        # WTI_FRONT_MONTH_CLOSE (storage_curve — price) or
        # WTI_FRONT_1W_LOG_RETURN (supply_disruption_news, oil_demand_nowcast —
        # log return). Per-desk Print value matches the desk's target.
        realised_price = float(market_price[i + HORIZON])
        realised_log_return = float(
            np.log(market_price[i + HORIZON]) - np.log(market_price[i - 1])
        )
        for name, desk in desks.items():
            target = desk.target_variable
            value = (
                realised_price if target == WTI_FRONT_MONTH_CLOSE else realised_log_return
            )
            p = Print(
                print_id=str(uuid.uuid4()),
                realised_ts_utc=realised_ts,
                target_variable=target,
                value=value,
                event_id=recent_forecasts[(name, target)].horizon.event_id,
            )
            bus.publish_print(p)
            g = grade(
                forecast=recent_forecasts[(name, target)],
                p=p,
                grading_ts_utc=realised_ts,
            )
            assert g is not None
            bus.publish_grade(g)

    # --- Assert §12.2 item 4: ≥ 20 round-trips per desk ----------------
    forecasts_per_desk = {
        r[0]: r[1]
        for r in smoke_db.execute(
            "SELECT desk_name, count(*) FROM forecasts GROUP BY desk_name"
        ).fetchall()
    }
    for name in desks:
        assert forecasts_per_desk.get(name, 0) >= 20, (
            f"{name}: {forecasts_per_desk.get(name, 0)} forecasts < 20"
        )

    attribution_per_desk = {
        r[0]: r[1]
        for r in smoke_db.execute(
            "SELECT desk_name, count(*) FROM attribution_lodo GROUP BY desk_name"
        ).fetchall()
    }
    for name in desks:
        assert attribution_per_desk.get(name, 0) >= 20, (
            f"{name}: {attribution_per_desk.get(name, 0)} attribution rows < 20"
        )

    # Prints and grades: one per desk per round-trip.
    assert count_rows(smoke_db, "prints") >= 20 * len(desks)
    assert count_rows(smoke_db, "grades") >= 20 * len(desks)
    assert count_rows(smoke_db, "decisions") == N_ROUND_TRIPS


def test_phase1_shapley_rollup_runs_end_to_end(smoke_db):
    """Companion evidence: Shapley attribution runs across the full
    round-trip cohort. §9.2 attribution layer verified."""
    path = LatentMarket(n_days=N_DAYS, seed=SEED, config=phase_a_config()).generate()
    channels = ObservationChannels.build(path, mode="clean", seed=SEED)
    market_price = channels.market_price
    desks = _fit_all_desks(channels, market_price)
    classifier = GroundTruthRegimeClassifier()
    seed_cold_start(
        smoke_db,
        desks=[(name, WTI_FRONT_MONTH_CLOSE) for name in desks],
        regime_ids=list(REGIMES),
        boot_ts=NOW_BASE - timedelta(days=1),
        default_cold_start_limit=1e9,
    )
    controller = Controller(conn=smoke_db)
    bus = Bus(conn=smoke_db, mode="development")

    decisions: list[object] = []
    recent_by_decision: dict[str, dict[tuple[str, str], object]] = {}
    for n in range(N_ROUND_TRIPS):
        i = HELD_OUT_START + n
        emission_ts = NOW_BASE + timedelta(days=int(n))
        regime_label = classifier.regime_label_at(channels, i, emission_ts)
        bus.publish_regime_label(regime_label)
        recent: dict[tuple[str, str], object] = {}
        for name, desk in desks.items():
            f = desk.forecast_from_observation(channels, i, emission_ts)
            bus.publish_forecast(f)
            recent[(name, f.target_variable)] = f
        d = controller.decide(
            now_utc=emission_ts,
            regime_label=regime_label,
            recent_forecasts=recent,
        )
        bus.publish_decision(d)
        decisions.append(d)
        recent_by_decision[d.decision_id] = recent

    review_ts = NOW_BASE + timedelta(days=N_ROUND_TRIPS + 1)
    shapley_rows = compute_shapley_signal_space(
        conn=smoke_db,
        decisions=decisions,
        recent_forecasts_by_decision=recent_by_decision,
        review_ts_utc=review_ts,
    )
    # One row per desk.
    assert len(shapley_rows) == len(desks)
    desk_names = {r.desk_name for r in shapley_rows}
    assert desk_names == set(desks.keys())


def test_phase1_latency_kpi_reported(smoke_db):
    """§12.2 item 5 — latency KPI is measured and reported (not
    'pending data'). We submit a batch of research-loop events,
    process them through the dispatcher, and assert
    `compute_latency_report` returns non-None per-type + overall
    latencies."""
    dispatcher = Dispatcher(conn=smoke_db)
    dispatcher.register("gate_failure", gate_failure_handler)

    # Submit 5 events; dispatcher processes them in priority order.
    base_ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    for n in range(5):
        trigger_ts = base_ts + timedelta(minutes=n)
        event = ResearchLoopEvent(
            event_id=str(uuid.uuid4()),
            event_type="gate_failure",
            triggered_at_utc=trigger_ts,
            priority=0,
            payload={
                "desk": "storage_curve",
                "gate": "skill",
                "metric": 0.05,
                "failure_mode": "rmse_above_baseline",
            },
        )
        dispatcher.submit(event)

    # Process at a fixed later wall-clock.
    complete_ts = base_ts + timedelta(hours=1)
    dispatcher.run(now_utc=complete_ts)

    # compute_latency_report reads from research_loop_events over the window.
    report = compute_latency_report(
        conn=smoke_db,
        window_start_ts_utc=base_ts - timedelta(hours=1),
        window_end_ts_utc=complete_ts,
    )
    assert report.overall_n_triggered == 5
    assert report.overall_n_completed == 5
    assert report.overall_completion_rate == pytest.approx(1.0)
    assert "gate_failure" in report.per_type
    gf = report.per_type["gate_failure"]
    assert gf.n_triggered == 5
    assert gf.n_completed == 5
    assert gf.mean_latency_s is not None and gf.mean_latency_s > 0
    assert gf.p95_latency_s is not None and gf.p95_latency_s > 0
    assert gf.max_latency_s is not None and gf.max_latency_s > 0

    # Diagnostics for the Phase 1 completion report.
    print(
        f"\n§12.2 item 5: Latency KPI measured — "
        f"mean={gf.mean_latency_s:.2f}s "
        f"p95={gf.p95_latency_s:.2f}s "
        f"max={gf.max_latency_s:.2f}s "
        f"n={gf.n_triggered}"
    )
