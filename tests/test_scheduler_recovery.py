"""Tests for scheduler.check_incident_recoveries +
scheduler.submit_feed_reliability_review (spec §14.5 v1.7 recovery
path, §6.2 review submitter).

These close two loose ends from the feed-reliability loop:
  - Closing a feed_incidents row when Prints resume AND resetting the
    Page-Hinkley detector so the next drift episode starts fresh.
  - Submitting a feed_reliability_review event periodically.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from persistence import (
    connect,
    get_feed_latency_state,
    get_open_feed_incidents,
    init_db,
    open_feed_incident,
    upsert_feed_latency_state,
)
from research_loop import Dispatcher
from scheduler import DataSource, ScheduledEvent, Scheduler

NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "sched_recov.duckdb")
    init_db(c)
    yield c
    c.close()


def _scheduler_with_one_feed(feed_name: str = "eia_wpsr") -> Scheduler:
    ev = ScheduledEvent(
        event_id=feed_name,
        description="test feed",
        cron="0 0 * * *",
        tz="UTC",
        target_variable="wti_front_month_close",
    )
    ds = DataSource(
        feed_name=feed_name,
        description="test",
        tolerance_minutes=120,
        consumed_by=("supply",),
    )
    return Scheduler(events=[ev], data_sources={feed_name: ds})


# ---------------------------------------------------------------------------
# check_incident_recoveries
# ---------------------------------------------------------------------------


def test_check_incident_recoveries_closes_on_fresh_print(conn):
    """Open an incident; after the next scheduled firing gets a
    timely Print, the incident closes and the PH state resets."""
    sched = _scheduler_with_one_feed("eia_wpsr")
    incident_open_ts = NOW - timedelta(days=3, hours=2)
    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=incident_open_ts,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    # Simulate PH state indicating prior trip — must reset on recovery.
    upsert_feed_latency_state(
        conn,
        feed_name="eia_wpsr",
        cumulative_sum=75.0,
        min_cumulative=0.0,
        n_observations=20,
        last_update_ts_utc=incident_open_ts,
        tripped=True,
    )

    # Next daily cron firing after incident_open_ts is at 00:00 UTC the
    # following day. Supply a timely Print.
    firings = sched.firings_between(incident_open_ts, NOW)
    assert len(firings) >= 1
    next_scheduled = firings[0][1]
    prints_for_feed = {"eia_wpsr": [next_scheduled + timedelta(minutes=5)]}

    closed = sched.check_incident_recoveries(conn, NOW, prints_for_feed)
    assert closed == ["eia_wpsr"]

    # Registry: incident closed.
    assert get_open_feed_incidents(conn) == []
    # PH detector: reset.
    state = get_feed_latency_state(conn, "eia_wpsr")
    assert state is not None
    assert state["tripped"] is False
    assert state["cumulative_sum"] == pytest.approx(0.0)
    assert state["n_observations"] == 0


def test_check_incident_recoveries_no_close_when_no_fresh_print(conn):
    """Incident is open AND no Print arrived since the next scheduled
    firing → recovery is not declared."""
    sched = _scheduler_with_one_feed("eia_wpsr")
    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW - timedelta(days=3),
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    closed = sched.check_incident_recoveries(conn, NOW, {"eia_wpsr": []})
    assert closed == []
    assert len(get_open_feed_incidents(conn)) == 1


def test_check_incident_recoveries_ignores_pre_incident_prints(conn):
    """Prints that arrived BEFORE the incident was opened must NOT
    count as recovery — they were the data that was already classified
    as late."""
    sched = _scheduler_with_one_feed("eia_wpsr")
    incident_open_ts = NOW - timedelta(days=1)
    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=incident_open_ts,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    # Print that landed 5 days before the incident was opened — stale.
    ancient_print = incident_open_ts - timedelta(days=5)
    closed = sched.check_incident_recoveries(conn, NOW, {"eia_wpsr": [ancient_print]})
    assert closed == []


def test_check_incident_recoveries_noop_when_no_open_incidents(conn):
    sched = _scheduler_with_one_feed("eia_wpsr")
    # No incidents at all.
    assert sched.check_incident_recoveries(conn, NOW, {}) == []


# ---------------------------------------------------------------------------
# submit_feed_reliability_review
# ---------------------------------------------------------------------------


def test_submit_feed_reliability_review_defaults_to_all_feeds(conn):
    sched = Scheduler(
        events=[],
        data_sources={
            "eia_wpsr": DataSource("eia_wpsr", "", 120, ("supply",)),
            "cftc_cot": DataSource("cftc_cot", "", 120, ("storage_curve",)),
        },
    )
    dispatcher = Dispatcher(conn=conn)
    event = sched.submit_feed_reliability_review(dispatcher, now_utc=NOW)
    assert event.event_type == "feed_reliability_review"
    assert event.priority == 2
    assert event.triggered_at_utc == NOW
    # Defaults to sorted list of all configured feeds.
    assert event.payload["feed_names"] == ["cftc_cot", "eia_wpsr"]
    # Persisted.
    pending = dispatcher.pending_events()
    assert len(pending) == 1
    assert pending[0].event_id == event.event_id


def test_submit_feed_reliability_review_accepts_explicit_feed_list(conn):
    sched = Scheduler(
        events=[],
        data_sources={
            "eia_wpsr": DataSource("eia_wpsr", "", 120, ("supply",)),
            "cftc_cot": DataSource("cftc_cot", "", 120, ("storage_curve",)),
        },
    )
    dispatcher = Dispatcher(conn=conn)
    event = sched.submit_feed_reliability_review(dispatcher, now_utc=NOW, feed_names=["eia_wpsr"])
    assert event.payload["feed_names"] == ["eia_wpsr"]


def test_submit_feed_reliability_review_accepts_overrides(conn):
    sched = _scheduler_with_one_feed("eia_wpsr")
    dispatcher = Dispatcher(conn=conn)
    event = sched.submit_feed_reliability_review(
        dispatcher,
        now_utc=NOW,
        feed_names=["eia_wpsr"],
        lookback_days=60,
        retirement_threshold=10,
        max_retirements_per_7_days=5,
    )
    assert event.payload["lookback_days"] == 60
    assert event.payload["retirement_threshold"] == 10
    assert event.payload["max_retirements_per_7_days"] == 5


def test_submit_and_dispatch_end_to_end(conn):
    """Submit the event + register the handler + run the dispatcher →
    the review fires, writes its artefact, and completes."""
    from research_loop import feed_reliability_review_handler

    sched = _scheduler_with_one_feed("eia_wpsr")
    dispatcher = Dispatcher(conn=conn)
    dispatcher.register("feed_reliability_review", feed_reliability_review_handler)
    sched.submit_feed_reliability_review(dispatcher, now_utc=NOW, feed_names=["eia_wpsr"])
    processed = dispatcher.run(now_utc=NOW)
    assert len(processed) == 1
    event_out, result = processed[0]
    assert event_out.event_type == "feed_reliability_review"
    import json

    summary = json.loads(result.artefact)
    assert summary["handler"] == "feed_reliability_review_v0.2"
    assert "eia_wpsr" in summary["feeds_reviewed"]
