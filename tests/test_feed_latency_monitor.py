"""Tests for Page-Hinkley change-point detector (spec §14.5 v1.7,
Layer 3).

Covers:
  - Pure-function Page-Hinkley recurrence on synthetic series.
  - Persistence round-trip (detector state survives process restart).
  - Reset semantics after incident closure.
  - Determinism: same input sequence → same trip index.
  - Scheduler integration: check_latency_drift fires preemptive
    data_ingestion_failure with detected_by='page_hinkley' on drift
    BEFORE the tolerance-window path would.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from persistence import (
    connect,
    get_feed_latency_state,
    init_db,
)
from research_loop.feed_latency_monitor import (
    PAGE_HINKLEY_DELTA,
    PAGE_HINKLEY_THRESHOLD,
    PageHinkleyState,
    initial_state,
    load_or_initial,
    observe_latency,
    persist,
    reset_for_feed,
    update_page_hinkley,
)

NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "ph.duckdb")
    init_db(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# initial_state
# ---------------------------------------------------------------------------


def test_initial_state_is_zero():
    s = initial_state("eia_wpsr")
    assert s.feed_name == "eia_wpsr"
    assert s.cumulative_sum == 0.0
    assert s.min_cumulative == 0.0
    assert s.n_observations == 0
    assert s.last_update_ts_utc is None
    assert s.tripped is False


# ---------------------------------------------------------------------------
# update_page_hinkley — pure recurrence
# ---------------------------------------------------------------------------


def test_zero_latency_never_trips():
    state = initial_state("eia_wpsr")
    for i in range(1000):
        state, newly = update_page_hinkley(
            state, 0.0, NOW + timedelta(minutes=i), threshold=PAGE_HINKLEY_THRESHOLD
        )
        assert newly is False
    assert state.tripped is False
    # min tracks cumulative_sum downward (pure delta accumulation).
    assert state.cumulative_sum < 0.0
    assert state.min_cumulative == pytest.approx(state.cumulative_sum)


def test_single_large_spike_trips():
    """One 100-second spike (delta=0.005, threshold=50) trips immediately."""
    state = initial_state("eia_wpsr")
    state, newly = update_page_hinkley(state, 100.0, NOW)
    assert newly is True
    assert state.tripped is True


def test_slow_drift_eventually_trips():
    """Ramp: 0,0,0,0,0,10,20,30,40,... (drift). Trips after accumulated
    positive statistic > threshold."""
    state = initial_state("eia_wpsr")
    trip_index: int | None = None
    for i, x in enumerate([0, 0, 0, 0, 0, 10, 20, 30, 40, 50, 60, 70]):
        state, newly = update_page_hinkley(state, float(x), NOW + timedelta(minutes=i))
        if newly:
            trip_index = i
            break
    assert trip_index is not None
    # Must happen during the ramp phase, not in the zeros.
    assert trip_index >= 5


def test_already_tripped_does_not_newly_trip_again():
    """Once tripped, subsequent updates return newly_tripped=False
    even if the statistic stays above threshold."""
    state = initial_state("eia_wpsr")
    state, first_newly = update_page_hinkley(state, 100.0, NOW)
    assert first_newly is True
    assert state.tripped is True

    state, second_newly = update_page_hinkley(state, 200.0, NOW + timedelta(minutes=1))
    assert second_newly is False
    assert state.tripped is True  # still tripped


def test_update_rejects_negative_latency():
    state = initial_state("eia_wpsr")
    with pytest.raises(ValueError, match="non-negative"):
        update_page_hinkley(state, -1.0, NOW)


def test_update_rejects_naive_timestamp():
    state = initial_state("eia_wpsr")
    with pytest.raises(ValueError, match="timezone-aware"):
        update_page_hinkley(state, 0.0, datetime(2026, 4, 17, 10, 0, 0))


# ---------------------------------------------------------------------------
# Determinism — same series → same trip index
# ---------------------------------------------------------------------------


def test_same_series_trips_at_same_index():
    """Replay determinism: running the same input stream twice from a
    fresh state gives the same trip point. The Page-Hinkley recurrence
    is deterministic by construction; this test pins that invariant."""
    series = [0.0, 1.0, 5.0, 10.0, 20.0, 30.0, 50.0, 80.0]

    def _run_to_trip(series: list[float]) -> int | None:
        state = initial_state("eia_wpsr")
        for i, x in enumerate(series):
            state, newly = update_page_hinkley(state, x, NOW + timedelta(seconds=i))
            if newly:
                return i
        return None

    first = _run_to_trip(series)
    second = _run_to_trip(series)
    assert first == second
    assert first is not None


# ---------------------------------------------------------------------------
# Persistence round-trip
# ---------------------------------------------------------------------------


def test_load_or_initial_fresh_returns_zero_state(conn):
    s = load_or_initial(conn, "eia_wpsr")
    assert s.n_observations == 0
    assert s.tripped is False
    assert s.cumulative_sum == 0.0


def test_persist_and_reload_roundtrip(conn):
    s = initial_state("eia_wpsr")
    s, _ = update_page_hinkley(s, 100.0, NOW)
    persist(conn, s)

    loaded = load_or_initial(conn, "eia_wpsr")
    assert loaded.feed_name == s.feed_name
    assert loaded.cumulative_sum == pytest.approx(s.cumulative_sum)
    assert loaded.min_cumulative == pytest.approx(s.min_cumulative)
    assert loaded.n_observations == s.n_observations
    assert loaded.last_update_ts_utc == s.last_update_ts_utc
    assert loaded.tripped == s.tripped


def test_observe_latency_updates_and_persists(conn):
    state1, newly1 = observe_latency(conn, feed_name="eia_wpsr", latency_seconds=100.0, now_utc=NOW)
    assert newly1 is True
    # Persisted — a second call loads this state.
    state2, newly2 = observe_latency(
        conn,
        feed_name="eia_wpsr",
        latency_seconds=0.0,
        now_utc=NOW + timedelta(minutes=1),
    )
    assert state2.n_observations == 2
    assert state2.tripped is True  # still tripped
    assert newly2 is False  # not newly


# ---------------------------------------------------------------------------
# reset_for_feed
# ---------------------------------------------------------------------------


def test_reset_for_feed_zeros_state(conn):
    observe_latency(conn, feed_name="eia_wpsr", latency_seconds=500.0, now_utc=NOW)
    row = get_feed_latency_state(conn, "eia_wpsr")
    assert row is not None
    assert row["tripped"] is True

    reset_for_feed(conn, "eia_wpsr")
    row = get_feed_latency_state(conn, "eia_wpsr")
    assert row is not None
    assert row["tripped"] is False
    assert row["cumulative_sum"] == pytest.approx(0.0)
    assert row["min_cumulative"] == pytest.approx(0.0)
    assert row["n_observations"] == 0


# ---------------------------------------------------------------------------
# Scheduler integration: check_latency_drift
# ---------------------------------------------------------------------------


def _scheduler_with_one_feed(feed_name: str = "eia_wpsr"):
    """Build a minimal Scheduler with one scheduled event that fires
    daily at 00:00 UTC."""
    from scheduler import DataSource, ScheduledEvent, Scheduler

    ev = ScheduledEvent(
        event_id=feed_name,
        description="test feed",
        cron="0 0 * * *",  # daily at 00:00
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


def test_check_latency_drift_fires_preemptive_event(conn):
    """Every Print arrives 60 seconds late — within the 120-minute
    tolerance so the tolerance-window path would NOT fire. But the PH
    detector accumulates across firings and trips → emits a
    data_ingestion_failure with detected_by='page_hinkley'."""
    sched = _scheduler_with_one_feed("eia_wpsr")
    observe_ts = NOW.replace(hour=12, minute=0, second=0, microsecond=0)
    firings = sched.firings_between(observe_ts - timedelta(days=14), observe_ts)
    # Arrival = scheduled + 60 seconds for every firing — consistent
    # small latency that PH should eventually register as drift.
    prints_by_feed = {
        "eia_wpsr": [scheduled_ts + timedelta(seconds=60) for _, scheduled_ts in firings]
    }
    emitted = sched.check_latency_drift(conn, observe_ts, prints_by_feed)
    assert len(emitted) >= 1
    first = emitted[0]
    assert first.event_type == "data_ingestion_failure"
    assert first.payload["detected_by"] == "page_hinkley"
    assert first.payload["feed_name"] == "eia_wpsr"


def test_check_latency_drift_no_fire_when_punctual(conn):
    """Prints arrive exactly on schedule → latency=0 → PH never trips
    → no events emitted. Test provides a Print for EVERY scheduled
    firing in the 14-day lookback so no "latency = now - scheduled"
    fallback fires."""
    sched = _scheduler_with_one_feed("eia_wpsr")
    # observe_ts far enough from any cron boundary that we can pre-
    # populate prints for every scheduled firing in the lookback.
    observe_ts = NOW.replace(hour=12, minute=0, second=0, microsecond=0)
    # Provide one Print per scheduled firing in [observe_ts-14d, observe_ts].
    firings = sched.firings_between(observe_ts - timedelta(days=14), observe_ts)
    prints_by_feed = {"eia_wpsr": [scheduled_ts for _, scheduled_ts in firings]}
    emitted = sched.check_latency_drift(conn, observe_ts, prints_by_feed)
    assert emitted == []


def test_check_latency_drift_defers_to_open_incident(conn):
    """If a feed already has an open incident (scheduler-path fired
    first), PH does not emit a duplicate preemptive event — no matter
    what the detector sees. The PH state still updates (for diagnostic
    continuity), but emission is suppressed."""
    from persistence import open_feed_incident

    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW - timedelta(days=1),
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    sched = _scheduler_with_one_feed("eia_wpsr")
    observe_ts = NOW.replace(hour=12, minute=0, second=0, microsecond=0)
    firings = sched.firings_between(observe_ts - timedelta(days=14), observe_ts)
    # Arrival = scheduled + 60s for every firing — would trip PH.
    prints_by_feed = {
        "eia_wpsr": [scheduled_ts + timedelta(seconds=60) for _, scheduled_ts in firings]
    }
    emitted = sched.check_latency_drift(conn, observe_ts, prints_by_feed)
    assert emitted == []


# ---------------------------------------------------------------------------
# Defaults are stable
# ---------------------------------------------------------------------------


def test_page_hinkley_defaults_stable():
    assert PAGE_HINKLEY_DELTA == 0.005
    assert PAGE_HINKLEY_THRESHOLD == 50.0


def test_page_hinkley_state_is_frozen():
    """PageHinkleyState is a frozen dataclass — attempt to mutate
    should raise FrozenInstanceError."""
    from dataclasses import FrozenInstanceError

    state = PageHinkleyState(
        feed_name="x",
        cumulative_sum=0.0,
        min_cumulative=0.0,
        n_observations=0,
        last_update_ts_utc=None,
        tripped=False,
    )
    with pytest.raises(FrozenInstanceError):
        state.cumulative_sum = 1.0  # type: ignore[misc]
