"""Tests for research_loop.kpi.compute_latency_report (§12.2 point 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from contracts.v1 import ResearchLoopEvent
from persistence import connect, init_db, insert_research_loop_event
from research_loop import Dispatcher, HandlerResult, compute_latency_report


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "kpi.duckdb")
    init_db(c)
    yield c
    c.close()


def _event(
    event_id: str, event_type: str, triggered: datetime, completed: datetime | None = None
) -> ResearchLoopEvent:
    return ResearchLoopEvent(
        event_id=event_id,
        event_type=event_type,
        triggered_at_utc=triggered,
        priority=5,
        payload={},
        completed_at_utc=completed,
    )


def _insert_completed(
    conn,
    event_id: str,
    event_type: str,
    triggered: datetime,
    completed: datetime,
) -> None:
    """Insert an event with its completed_at_utc set directly (bypassing
    Dispatcher for the KPI math tests)."""
    # Persist as pending, then UPDATE (mirrors the real dispatcher flow).
    insert_research_loop_event(conn, _event(event_id, event_type, triggered))
    conn.execute(
        "UPDATE research_loop_events SET completed_at_utc = ?, "
        "produced_artefact = ? WHERE event_id = ?",
        [completed, "ok", event_id],
    )


# ---------------------------------------------------------------------------
# Basic shape + empty window
# ---------------------------------------------------------------------------


def test_empty_window_returns_zero_report(conn):
    start = datetime(2026, 4, 16, 0, 0, 0, tzinfo=UTC)
    end = datetime(2026, 4, 17, 0, 0, 0, tzinfo=UTC)
    report = compute_latency_report(conn, window_start_ts_utc=start, window_end_ts_utc=end)
    assert report.per_type == {}
    assert report.overall_n_triggered == 0
    assert report.overall_n_completed == 0
    assert report.overall_completion_rate == 0.0


def test_single_event_type_mean_median_p95(conn):
    base = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    # Three events with latencies 1s, 5s, 10s
    _insert_completed(conn, "e1", "gate_failure", base, base + timedelta(seconds=1))
    _insert_completed(
        conn,
        "e2",
        "gate_failure",
        base + timedelta(minutes=1),
        base + timedelta(minutes=1, seconds=5),
    )
    _insert_completed(
        conn,
        "e3",
        "gate_failure",
        base + timedelta(minutes=2),
        base + timedelta(minutes=2, seconds=10),
    )

    report = compute_latency_report(
        conn,
        window_start_ts_utc=base - timedelta(seconds=1),
        window_end_ts_utc=base + timedelta(hours=1),
    )
    gf = report.per_type["gate_failure"]
    assert gf.n_triggered == 3
    assert gf.n_completed == 3
    assert gf.completion_rate == 1.0
    # latencies: [1, 5, 10]; mean = 5.33, median = 5, p95 ≈ 10, max = 10
    assert gf.mean_latency_s == pytest.approx(16.0 / 3.0)
    assert gf.p50_latency_s == pytest.approx(5.0)
    assert gf.p95_latency_s == pytest.approx(10.0)
    assert gf.max_latency_s == pytest.approx(10.0)


def test_partial_completion_rate(conn):
    base = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    _insert_completed(conn, "e1", "regime_transition", base, base + timedelta(seconds=2))
    # Pending: triggered but not yet completed
    insert_research_loop_event(
        conn, _event("e2", "regime_transition", base + timedelta(seconds=30))
    )
    _insert_completed(
        conn,
        "e3",
        "regime_transition",
        base + timedelta(minutes=1),
        base + timedelta(minutes=1, seconds=4),
    )

    report = compute_latency_report(
        conn,
        window_start_ts_utc=base - timedelta(seconds=1),
        window_end_ts_utc=base + timedelta(hours=1),
    )
    rt = report.per_type["regime_transition"]
    assert rt.n_triggered == 3
    assert rt.n_completed == 2
    assert rt.completion_rate == pytest.approx(2.0 / 3.0)
    # Pending event isn't used in mean/p95
    assert rt.mean_latency_s == pytest.approx(3.0)


def test_per_type_breakdown(conn):
    base = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    _insert_completed(conn, "g1", "gate_failure", base, base + timedelta(seconds=1))
    _insert_completed(
        conn,
        "g2",
        "gate_failure",
        base + timedelta(minutes=1),
        base + timedelta(minutes=1, seconds=3),
    )
    _insert_completed(
        conn,
        "p1",
        "periodic_weekly",
        base + timedelta(minutes=2),
        base + timedelta(minutes=2, seconds=60),
    )

    report = compute_latency_report(
        conn,
        window_start_ts_utc=base - timedelta(seconds=1),
        window_end_ts_utc=base + timedelta(hours=1),
    )
    assert set(report.per_type.keys()) == {"gate_failure", "periodic_weekly"}
    assert report.per_type["gate_failure"].n_triggered == 2
    assert report.per_type["periodic_weekly"].n_triggered == 1
    assert report.per_type["periodic_weekly"].mean_latency_s == pytest.approx(60.0)


def test_window_filters_events_outside_range(conn):
    base = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    # Event triggered before window
    _insert_completed(
        conn,
        "old",
        "gate_failure",
        base - timedelta(days=1),
        base - timedelta(days=1) + timedelta(seconds=2),
    )
    # Event triggered after window
    _insert_completed(
        conn,
        "future",
        "gate_failure",
        base + timedelta(days=1),
        base + timedelta(days=1) + timedelta(seconds=2),
    )
    # Event inside window
    _insert_completed(conn, "now", "gate_failure", base, base + timedelta(seconds=3))

    report = compute_latency_report(
        conn,
        window_start_ts_utc=base - timedelta(hours=1),
        window_end_ts_utc=base + timedelta(hours=1),
    )
    assert report.per_type["gate_failure"].n_triggered == 1


def test_all_pending_produces_none_latency(conn):
    base = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    insert_research_loop_event(conn, _event("p1", "desk_staleness", base))
    insert_research_loop_event(conn, _event("p2", "desk_staleness", base + timedelta(seconds=10)))

    report = compute_latency_report(
        conn,
        window_start_ts_utc=base - timedelta(seconds=1),
        window_end_ts_utc=base + timedelta(hours=1),
    )
    ds = report.per_type["desk_staleness"]
    assert ds.n_triggered == 2
    assert ds.n_completed == 0
    assert ds.completion_rate == 0.0
    assert ds.mean_latency_s is None
    assert ds.p95_latency_s is None


def test_overall_aggregation_across_types(conn):
    base = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    _insert_completed(conn, "a", "gate_failure", base, base + timedelta(seconds=1))
    _insert_completed(
        conn, "b", "periodic_weekly", base + timedelta(seconds=1), base + timedelta(seconds=6)
    )
    insert_research_loop_event(conn, _event("c", "regime_transition", base + timedelta(seconds=2)))

    report = compute_latency_report(
        conn,
        window_start_ts_utc=base - timedelta(seconds=1),
        window_end_ts_utc=base + timedelta(hours=1),
    )
    assert report.overall_n_triggered == 3
    assert report.overall_n_completed == 2
    assert report.overall_completion_rate == pytest.approx(2.0 / 3.0)


# ---------------------------------------------------------------------------
# End-to-end integration with Dispatcher
# ---------------------------------------------------------------------------


def test_dispatcher_run_produces_measurable_latency(conn):
    """Real dispatcher run → KPI report captures its timing."""
    trigger_ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    complete_ts = datetime(2026, 4, 16, 10, 0, 30, tzinfo=UTC)

    dispatcher = Dispatcher(conn=conn)
    dispatcher.register("gate_failure", lambda _c, _e: HandlerResult(artefact="ok"))
    dispatcher.submit(
        ResearchLoopEvent(
            event_id="e1",
            event_type="gate_failure",
            triggered_at_utc=trigger_ts,
            priority=0,
            payload={
                "desk": "storage_curve",
                "gate": "skill",
                "metric": 0.0,
                "failure_mode": "test",
            },
        )
    )
    processed = dispatcher.run(now_utc=complete_ts)
    assert len(processed) == 1

    report = compute_latency_report(
        conn,
        window_start_ts_utc=trigger_ts - timedelta(seconds=1),
        window_end_ts_utc=complete_ts + timedelta(seconds=1),
    )
    gf = report.per_type["gate_failure"]
    assert gf.n_completed == 1
    assert gf.mean_latency_s == pytest.approx(30.0)
