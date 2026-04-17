"""Research-loop dispatcher + periodic weekly handler tests (spec §6).

Covers:
  - Dispatcher processes pending events in priority order (0 < 9).
  - Event with no registered handler is skipped (stays pending).
  - Handler completion writes completed_at_utc + produced_artefact.
  - periodic_weekly_handler emits a Shapley rollup JSON over a window
    of Decisions persisted via the Controller.
  - periodic_weekly_handler rejects the wrong event type.
  - Empty-window rollup returns n_decisions=0 summary without errors.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    ResearchLoopEvent,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence.db import connect, init_db, insert_forecast
from research_loop import (
    Dispatcher,
    HandlerResult,
    data_ingestion_failure_handler,
    gate_failure_handler,
    periodic_weekly_handler,
    regime_transition_handler,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "rl.duckdb")
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


def _fcast(desk: str, value: float, ts: datetime) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=ts,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=ts),
        point_estimate=value,
        uncertainty=UncertaintyInterval(level=0.8, lower=value - 5.0, upper=value + 5.0),
        directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
        staleness=False,
        confidence=1.0,
        provenance=_prov(desk),
    )


def _regime(ts: datetime) -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=ts,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


# ---------------------------------------------------------------------------
# Dispatcher behaviour
# ---------------------------------------------------------------------------


def test_dispatcher_processes_events_in_priority_order(conn):
    calls: list[str] = []

    def handler_high(conn, event):
        calls.append("high")
        return HandlerResult(artefact="hi")

    def handler_low(conn, event):
        calls.append("low")
        return HandlerResult(artefact="lo")

    d = Dispatcher(conn=conn)
    d.register("gate_failure", handler_high)  # prio 0
    d.register("desk_staleness", handler_low)  # prio 3

    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    d.submit(
        ResearchLoopEvent(
            event_id="low1",
            event_type="desk_staleness",
            triggered_at_utc=ts,
            priority=3,
            payload={"desk": "supply"},
        )
    )
    d.submit(
        ResearchLoopEvent(
            event_id="high1",
            event_type="gate_failure",
            triggered_at_utc=ts,
            priority=0,
            payload={"desk": "storage_curve", "gate": "skill"},
        )
    )
    processed = d.run(now_utc=ts)
    assert [p[0].event_id for p in processed] == ["high1", "low1"]
    assert calls == ["high", "low"]


def test_dispatcher_skips_events_without_handler(conn):
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    d = Dispatcher(conn=conn)
    d.submit(
        ResearchLoopEvent(
            event_id="orphan",
            event_type="regime_transition",
            triggered_at_utc=ts,
            priority=1,
            payload={"from": "a", "to": "b"},
        )
    )
    processed = d.run(now_utc=ts)
    assert processed == []
    pending_after = d.pending_events()
    assert [e.event_id for e in pending_after] == ["orphan"]


def test_dispatcher_marks_completed_and_stores_artefact(conn):
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    later = datetime(2026, 4, 16, 10, 5, 0, tzinfo=UTC)

    def handler(conn, event):
        return HandlerResult(artefact="ok", notes="nominal")

    d = Dispatcher(conn=conn)
    d.register("gate_failure", handler)
    d.submit(
        ResearchLoopEvent(
            event_id="e1",
            event_type="gate_failure",
            triggered_at_utc=ts,
            priority=0,
            payload={"desk": "storage_curve"},
        )
    )
    d.run(now_utc=later)
    assert d.pending_events() == []

    row = conn.execute(
        "SELECT completed_at_utc, produced_artefact FROM research_loop_events WHERE event_id = ?",
        ["e1"],
    ).fetchone()
    assert row[0] == later
    assert row[1] == "ok"


def test_dispatcher_rejects_naive_now_utc(conn):
    d = Dispatcher(conn=conn)
    with pytest.raises(ValueError, match="timezone-aware"):
        d.run(now_utc=datetime(2026, 4, 16, 10, 0, 0))


# ---------------------------------------------------------------------------
# periodic_weekly_handler
# ---------------------------------------------------------------------------


def test_periodic_weekly_handler_rollup_on_two_decisions(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 4, 16, 11, 0, 0, tzinfo=UTC)
    window_start = datetime(2026, 4, 16, 0, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 4, 17, 0, 0, 0, tzinfo=UTC)

    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("macro", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)

    fcasts1 = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 80.0, t1),
        ("macro", WTI_FRONT_MONTH_CLOSE): _fcast("macro", 100.0, t1),
    }
    fcasts2 = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 160.0, t2),
        ("macro", WTI_FRONT_MONTH_CLOSE): _fcast("macro", 200.0, t2),
    }
    # Persist the Forecasts so the handler can reconstruct them via input_forecast_ids.
    for f in [*fcasts1.values(), *fcasts2.values()]:
        insert_forecast(conn, f)
    d1 = ctrl.decide(now_utc=t1, regime_label=_regime(t1), recent_forecasts=fcasts1)
    d2 = ctrl.decide(now_utc=t2, regime_label=_regime(t2), recent_forecasts=fcasts2)
    # Persist the decisions for the handler's query.
    from persistence.db import insert_decision

    insert_decision(conn, d1)
    insert_decision(conn, d2)

    event = ResearchLoopEvent(
        event_id="weekly-1",
        event_type="periodic_weekly",
        triggered_at_utc=window_end,
        priority=5,
        payload={
            "window_start_ts_utc": window_start.isoformat(),
            "window_end_ts_utc": window_end.isoformat(),
        },
    )
    result = periodic_weekly_handler(conn, event)
    summary = json.loads(result.artefact)

    assert summary["n_decisions"] == 2
    assert summary["window"]["start"] == window_start.isoformat()
    assert summary["window"]["end"] == window_end.isoformat()
    by_desk = {row["desk"]: row for row in summary["shapley"]}
    # From test_shapley_window_aggregation_two_decisions: avg Shapley
    # values are storage=60, macro=75 when both desks double their
    # forecasts from decision 1 to decision 2.
    assert by_desk["storage_curve"]["value"] == pytest.approx(60.0)
    assert by_desk["macro"]["value"] == pytest.approx(75.0)
    assert by_desk["storage_curve"]["n"] == 2
    assert by_desk["macro"]["n"] == 2


def test_periodic_weekly_handler_empty_window(conn):
    window_start = datetime(2026, 4, 16, 0, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 4, 17, 0, 0, 0, tzinfo=UTC)
    event = ResearchLoopEvent(
        event_id="weekly-empty",
        event_type="periodic_weekly",
        triggered_at_utc=window_end,
        priority=5,
        payload={
            "window_start_ts_utc": window_start.isoformat(),
            "window_end_ts_utc": window_end.isoformat(),
        },
    )
    result = periodic_weekly_handler(conn, event)
    summary = json.loads(result.artefact)
    assert summary["n_decisions"] == 0
    assert summary["shapley"] == []


def test_periodic_weekly_handler_rejects_wrong_event_type(conn):
    event = ResearchLoopEvent(
        event_id="wrong",
        event_type="gate_failure",
        triggered_at_utc=datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC),
        priority=0,
        payload={},
    )
    with pytest.raises(ValueError, match="wrong event type"):
        periodic_weekly_handler(conn, event)


def test_periodic_weekly_handler_bad_payload_returns_error_artefact(conn):
    event = ResearchLoopEvent(
        event_id="weekly-bad",
        event_type="periodic_weekly",
        triggered_at_utc=datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC),
        priority=5,
        payload={"not": "the right keys"},
    )
    result = periodic_weekly_handler(conn, event)
    summary = json.loads(result.artefact)
    assert "error" in summary


def test_dispatcher_wires_periodic_weekly_end_to_end(conn):
    """End-to-end: register handler, submit a periodic_weekly event,
    run the dispatcher, verify the artefact is persisted to the DB."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    t1 = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    window_start = datetime(2026, 4, 16, 0, 0, 0, tzinfo=UTC)
    window_end = datetime(2026, 4, 17, 0, 0, 0, tzinfo=UTC)

    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    f = _fcast("storage_curve", 80.0, t1)
    insert_forecast(conn, f)
    recent = {("storage_curve", WTI_FRONT_MONTH_CLOSE): f}
    decision = ctrl.decide(now_utc=t1, regime_label=_regime(t1), recent_forecasts=recent)
    from persistence.db import insert_decision

    insert_decision(conn, decision)

    dispatcher = Dispatcher(conn=conn)
    dispatcher.register("periodic_weekly", periodic_weekly_handler)
    dispatcher.submit(
        ResearchLoopEvent(
            event_id="weekly-1",
            event_type="periodic_weekly",
            triggered_at_utc=window_end,
            priority=5,
            payload={
                "window_start_ts_utc": window_start.isoformat(),
                "window_end_ts_utc": window_end.isoformat(),
            },
        )
    )
    processed = dispatcher.run(now_utc=window_end)
    assert len(processed) == 1
    event_out, result = processed[0]
    assert event_out.event_id == "weekly-1"
    artefact = json.loads(result.artefact)
    assert artefact["n_decisions"] == 1
    assert artefact["shapley"][0]["desk"] == "storage_curve"
    # And the DB was updated
    row = conn.execute(
        "SELECT completed_at_utc, produced_artefact FROM research_loop_events WHERE event_id = ?",
        ["weekly-1"],
    ).fetchone()
    assert row[0] == window_end
    assert json.loads(row[1])["n_decisions"] == 1


# ---------------------------------------------------------------------------
# Event-driven handlers (§6.2)
# ---------------------------------------------------------------------------


def test_gate_failure_handler_logs_structured_artefact(conn):
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    event = ResearchLoopEvent(
        event_id="gate-1",
        event_type="gate_failure",
        triggered_at_utc=ts,
        priority=0,
        payload={
            "desk": "storage_curve",
            "gate": "sign_preservation",
            "metric": -0.23,
            "failure_mode": "dev_test_sign_flip",
        },
    )
    result = gate_failure_handler(conn, event)
    artefact = json.loads(result.artefact)
    assert artefact["handler"] == "gate_failure_v0.2"
    assert artefact["desk"] == "storage_curve"
    assert artefact["gate"] == "sign_preservation"
    assert artefact["metric"] == pytest.approx(-0.23)
    assert artefact["failure_mode"] == "dev_test_sign_flip"
    assert artefact["action"] == "logged_pending_rca"


def test_gate_failure_handler_missing_payload_keys(conn):
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    event = ResearchLoopEvent(
        event_id="gate-bad",
        event_type="gate_failure",
        triggered_at_utc=ts,
        priority=0,
        payload={"desk": "s", "gate": "skill"},  # missing metric, failure_mode
    )
    result = gate_failure_handler(conn, event)
    artefact = json.loads(result.artefact)
    assert "error" in artefact
    assert "missing payload keys" in artefact["error"]


def test_gate_failure_handler_rejects_wrong_event_type(conn):
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    event = ResearchLoopEvent(
        event_id="wrong",
        event_type="periodic_weekly",
        triggered_at_utc=ts,
        priority=0,
        payload={},
    )
    with pytest.raises(ValueError, match="wrong event"):
        gate_failure_handler(conn, event)


def test_regime_transition_handler_logs_structured_artefact(conn):
    """No historical decisions for the to_regime → v0.2 fails safe with
    action='insufficient_history_for_refresh'."""
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    event = ResearchLoopEvent(
        event_id="rt-1",
        event_type="regime_transition",
        triggered_at_utc=ts,
        priority=1,
        payload={
            "from_regime": "regime_boot",
            "to_regime": "regime_contango",
            "probability": 0.82,
        },
    )
    result = regime_transition_handler(conn, event)
    artefact = json.loads(result.artefact)
    assert artefact["handler"] == "regime_transition_v0.2"
    assert artefact["from"] == "regime_boot"
    assert artefact["to"] == "regime_contango"
    assert artefact["probability"] == pytest.approx(0.82)
    assert artefact["action"] == "insufficient_history_for_refresh"
    assert artefact["refresh_detail"]["n_decisions"] == 0


def test_data_ingestion_failure_handler_opens_incident(conn):
    """v0.2: handler opens a feed_incidents row and returns the id in
    the artefact JSON."""
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    event = ResearchLoopEvent(
        event_id="di-1",
        event_type="data_ingestion_failure",
        triggered_at_utc=ts,
        priority=1,
        payload={
            "feed_name": "eia_wpsr",
            "scheduled_release_ts_utc": "2026-04-16T14:30:00+00:00",
            "affected_desks": ["storage_curve", "supply"],
        },
    )
    result = data_ingestion_failure_handler(conn, event)
    artefact = json.loads(result.artefact)
    assert artefact["handler"] == "data_ingestion_failure_v0.2"
    assert artefact["feed_name"] == "eia_wpsr"
    assert artefact["affected_desks"] == ["storage_curve", "supply"]
    assert artefact["action"] == "feed_incident_opened"
    assert artefact["feed_incident_id"]
    assert artefact["detected_by"] == "scheduler"

    # The DB row is visible via get_open_feed_incidents.
    from persistence import get_open_feed_incidents

    rows = get_open_feed_incidents(conn, "eia_wpsr")
    assert len(rows) == 1
    assert rows[0]["feed_incident_id"] == artefact["feed_incident_id"]
    assert rows[0]["opening_event_id"] == "di-1"


def test_data_ingestion_failure_handler_idempotent_on_duplicate(conn):
    """Duplicate fire for the same open feed returns the same
    feed_incident_id and does NOT write a duplicate row."""
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    base_payload = {
        "feed_name": "eia_wpsr",
        "scheduled_release_ts_utc": "2026-04-16T14:30:00+00:00",
        "affected_desks": ["supply"],
    }
    event1 = ResearchLoopEvent(
        event_id="di-1",
        event_type="data_ingestion_failure",
        triggered_at_utc=ts,
        priority=1,
        payload=base_payload,
    )
    event2 = ResearchLoopEvent(
        event_id="di-2",
        event_type="data_ingestion_failure",
        triggered_at_utc=ts,
        priority=1,
        payload=base_payload,
    )
    r1 = json.loads(data_ingestion_failure_handler(conn, event1).artefact)
    r2 = json.loads(data_ingestion_failure_handler(conn, event2).artefact)
    assert r1["feed_incident_id"] == r2["feed_incident_id"]
    rows = conn.execute(
        "SELECT count(*) FROM feed_incidents WHERE feed_name = ?", ["eia_wpsr"]
    ).fetchone()
    assert rows[0] == 1


def test_dispatcher_handles_all_three_event_types_in_priority_order(conn):
    """Priority 0 (gate_failure) fires before priorities 1 and 5. Each
    event dispatches to its registered handler; the DB row is marked
    completed and produced_artefact is populated."""
    ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)

    d = Dispatcher(conn=conn)
    d.register("gate_failure", gate_failure_handler)
    d.register("regime_transition", regime_transition_handler)
    d.register("data_ingestion_failure", data_ingestion_failure_handler)

    # Submit out-of-priority-order.
    d.submit(
        ResearchLoopEvent(
            event_id="di",
            event_type="data_ingestion_failure",
            triggered_at_utc=ts,
            priority=1,
            payload={
                "feed_name": "cftc_cot",
                "scheduled_release_ts_utc": ts.isoformat(),
                "affected_desks": ["storage_curve"],
            },
        )
    )
    d.submit(
        ResearchLoopEvent(
            event_id="rt",
            event_type="regime_transition",
            triggered_at_utc=ts,
            priority=1,
            payload={
                "from_regime": "regime_a",
                "to_regime": "regime_b",
                "probability": 0.9,
            },
        )
    )
    d.submit(
        ResearchLoopEvent(
            event_id="gf",
            event_type="gate_failure",
            triggered_at_utc=ts,
            priority=0,
            payload={
                "desk": "storage_curve",
                "gate": "skill",
                "metric": 0.05,
                "failure_mode": "rmse_worse_than_baseline",
            },
        )
    )

    processed = d.run(now_utc=ts)
    # gate_failure first (priority 0), then di and rt (priority 1, tied
    # on triggered_at → event_id ordering: "di" < "rt" lex).
    assert [p[0].event_id for p in processed] == ["gf", "di", "rt"]
    # All three completed in the DB.
    pending = d.pending_events()
    assert pending == []
