"""Tests for feed_incidents + feed_latency_state CRUD (spec §14.5, §7.2).

Commit 1 is pure infrastructure — no behaviour change. These tests
pin the contract of open/close semantics, idempotency, and read
shape before anything else consumes them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from persistence import (
    close_feed_incident,
    connect,
    count_feed_incidents_in_window,
    get_feed_latency_state,
    get_open_feed_incidents,
    init_db,
    open_feed_incident,
    upsert_feed_latency_state,
)

NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "fi.duckdb")
    init_db(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# open_feed_incident
# ---------------------------------------------------------------------------


def test_open_feed_incident_writes_row(conn):
    fid = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply", "demand"],
        detected_by="scheduler",
        opening_event_id="evt-1",
    )
    assert fid
    rows = get_open_feed_incidents(conn, "eia_wpsr")
    assert len(rows) == 1
    assert rows[0]["feed_incident_id"] == fid
    assert rows[0]["feed_name"] == "eia_wpsr"
    assert rows[0]["affected_desks"] == ["supply", "demand"]
    assert rows[0]["detected_by"] == "scheduler"
    assert rows[0]["opening_event_id"] == "evt-1"


def test_open_feed_incident_idempotent_on_duplicate(conn):
    """Duplicate open while the first is still open returns the same id
    and does NOT write a second row."""
    fid1 = open_feed_incident(
        conn,
        feed_name="cftc_cot",
        opened_ts_utc=NOW,
        affected_desks=["storage_curve"],
        detected_by="scheduler",
    )
    fid2 = open_feed_incident(
        conn,
        feed_name="cftc_cot",
        opened_ts_utc=NOW + timedelta(minutes=5),
        affected_desks=["storage_curve"],
        detected_by="scheduler",
    )
    assert fid1 == fid2
    rows = conn.execute(
        "SELECT count(*) FROM feed_incidents WHERE feed_name = ?",
        ["cftc_cot"],
    ).fetchone()
    assert rows[0] == 1


def test_open_feed_incident_allows_new_row_after_close(conn):
    """Once closed, the feed can open a fresh incident — the history
    retains both rows."""
    fid1 = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    close_feed_incident(
        conn,
        feed_incident_id=fid1,
        closed_ts_utc=NOW + timedelta(hours=1),
        resolution_artefact="resumed",
    )
    fid2 = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW + timedelta(hours=2),
        affected_desks=["supply"],
        detected_by="page_hinkley",
    )
    assert fid1 != fid2
    total = conn.execute(
        "SELECT count(*) FROM feed_incidents WHERE feed_name = ?",
        ["eia_wpsr"],
    ).fetchone()
    assert total[0] == 2
    open_only = get_open_feed_incidents(conn, "eia_wpsr")
    assert len(open_only) == 1
    assert open_only[0]["feed_incident_id"] == fid2


def test_open_feed_incident_rejects_naive_timestamp(conn):
    with pytest.raises(ValueError, match="timezone-aware"):
        open_feed_incident(
            conn,
            feed_name="eia_wpsr",
            opened_ts_utc=datetime(2026, 4, 17, 10, 0, 0),
            affected_desks=["supply"],
            detected_by="scheduler",
        )


def test_open_feed_incident_rejects_bad_detected_by(conn):
    """Schema CHECK constraint bites at insert time."""
    with pytest.raises(duckdb.ConstraintException):
        open_feed_incident(
            conn,
            feed_name="eia_wpsr",
            opened_ts_utc=NOW,
            affected_desks=["supply"],
            detected_by="gut_feel",  # not in CHECK list
        )


# ---------------------------------------------------------------------------
# close_feed_incident
# ---------------------------------------------------------------------------


def test_close_feed_incident_sets_closed_ts_and_artefact(conn):
    fid = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    close_ts = NOW + timedelta(hours=3)
    close_feed_incident(
        conn,
        feed_incident_id=fid,
        closed_ts_utc=close_ts,
        resolution_artefact="manual:operator_confirmed",
    )
    row = conn.execute(
        "SELECT closed_ts_utc, resolution_artefact FROM feed_incidents WHERE feed_incident_id = ?",
        [fid],
    ).fetchone()
    assert row[0] == close_ts
    assert row[1] == "manual:operator_confirmed"


def test_close_feed_incident_is_noop_on_already_closed(conn):
    """Calling close twice is safe — the second call does not overwrite
    the first close's timestamp/artefact."""
    fid = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    first_close = NOW + timedelta(hours=1)
    close_feed_incident(
        conn,
        feed_incident_id=fid,
        closed_ts_utc=first_close,
        resolution_artefact="a",
    )
    close_feed_incident(
        conn,
        feed_incident_id=fid,
        closed_ts_utc=NOW + timedelta(hours=99),
        resolution_artefact="b",
    )
    row = conn.execute(
        "SELECT closed_ts_utc, resolution_artefact FROM feed_incidents WHERE feed_incident_id = ?",
        [fid],
    ).fetchone()
    assert row[0] == first_close
    assert row[1] == "a"


def test_close_feed_incident_rejects_naive_timestamp(conn):
    with pytest.raises(ValueError, match="timezone-aware"):
        close_feed_incident(
            conn,
            feed_incident_id="any",
            closed_ts_utc=datetime(2026, 4, 17, 10, 0, 0),
            resolution_artefact="x",
        )


# ---------------------------------------------------------------------------
# get_open_feed_incidents
# ---------------------------------------------------------------------------


def test_get_open_feed_incidents_returns_only_open(conn):
    fid1 = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    open_feed_incident(
        conn,
        feed_name="cftc_cot",
        opened_ts_utc=NOW,
        affected_desks=["storage_curve"],
        detected_by="scheduler",
    )
    close_feed_incident(
        conn,
        feed_incident_id=fid1,
        closed_ts_utc=NOW + timedelta(hours=1),
        resolution_artefact="r",
    )
    all_open = get_open_feed_incidents(conn)
    assert len(all_open) == 1
    assert all_open[0]["feed_name"] == "cftc_cot"


def test_get_open_feed_incidents_filters_by_feed(conn):
    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    open_feed_incident(
        conn,
        feed_name="cftc_cot",
        opened_ts_utc=NOW,
        affected_desks=["storage_curve"],
        detected_by="scheduler",
    )
    assert len(get_open_feed_incidents(conn, "eia_wpsr")) == 1
    assert len(get_open_feed_incidents(conn, "cftc_cot")) == 1
    assert len(get_open_feed_incidents(conn, "nonexistent")) == 0


# ---------------------------------------------------------------------------
# count_feed_incidents_in_window
# ---------------------------------------------------------------------------


def test_count_feed_incidents_in_window_counts_open_and_closed(conn):
    fid1 = open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    close_feed_incident(
        conn,
        feed_incident_id=fid1,
        closed_ts_utc=NOW + timedelta(hours=1),
        resolution_artefact="r",
    )
    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW + timedelta(days=2),
        affected_desks=["supply"],
        detected_by="page_hinkley",
    )
    count = count_feed_incidents_in_window(
        conn,
        feed_name="eia_wpsr",
        start_ts=NOW - timedelta(days=1),
        end_ts=NOW + timedelta(days=3),
    )
    assert count == 2


def test_count_feed_incidents_in_window_excludes_outside(conn):
    open_feed_incident(
        conn,
        feed_name="eia_wpsr",
        opened_ts_utc=NOW,
        affected_desks=["supply"],
        detected_by="scheduler",
    )
    count_before = count_feed_incidents_in_window(
        conn,
        feed_name="eia_wpsr",
        start_ts=NOW - timedelta(days=30),
        end_ts=NOW - timedelta(days=1),
    )
    assert count_before == 0
    count_after = count_feed_incidents_in_window(
        conn,
        feed_name="eia_wpsr",
        start_ts=NOW + timedelta(days=1),
        end_ts=NOW + timedelta(days=30),
    )
    assert count_after == 0


def test_count_feed_incidents_rejects_naive(conn):
    with pytest.raises(ValueError, match="timezone-aware"):
        count_feed_incidents_in_window(
            conn,
            feed_name="eia_wpsr",
            start_ts=datetime(2026, 4, 1),
            end_ts=NOW,
        )


# ---------------------------------------------------------------------------
# feed_latency_state upsert + read
# ---------------------------------------------------------------------------


def test_upsert_feed_latency_state_first_insert(conn):
    upsert_feed_latency_state(
        conn,
        feed_name="eia_wpsr",
        cumulative_sum=1.23,
        min_cumulative=0.5,
        n_observations=10,
        last_update_ts_utc=NOW,
        tripped=False,
    )
    state = get_feed_latency_state(conn, "eia_wpsr")
    assert state is not None
    assert state["cumulative_sum"] == pytest.approx(1.23)
    assert state["min_cumulative"] == pytest.approx(0.5)
    assert state["n_observations"] == 10
    assert state["last_update_ts_utc"] == NOW
    assert state["tripped"] is False


def test_upsert_feed_latency_state_overwrites_same_feed(conn):
    upsert_feed_latency_state(
        conn,
        feed_name="eia_wpsr",
        cumulative_sum=1.0,
        min_cumulative=0.5,
        n_observations=5,
        last_update_ts_utc=NOW,
        tripped=False,
    )
    upsert_feed_latency_state(
        conn,
        feed_name="eia_wpsr",
        cumulative_sum=2.0,
        min_cumulative=0.0,
        n_observations=11,
        last_update_ts_utc=NOW + timedelta(hours=1),
        tripped=True,
    )
    state = get_feed_latency_state(conn, "eia_wpsr")
    assert state is not None
    assert state["cumulative_sum"] == pytest.approx(2.0)
    assert state["n_observations"] == 11
    assert state["tripped"] is True


def test_get_feed_latency_state_missing_returns_none(conn):
    assert get_feed_latency_state(conn, "never_seen") is None


def test_upsert_feed_latency_state_rejects_naive(conn):
    with pytest.raises(ValueError, match="timezone-aware"):
        upsert_feed_latency_state(
            conn,
            feed_name="eia_wpsr",
            cumulative_sum=0.0,
            min_cumulative=0.0,
            n_observations=0,
            last_update_ts_utc=datetime(2026, 4, 17),
            tripped=False,
        )
