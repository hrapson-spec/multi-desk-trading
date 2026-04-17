"""Unit tests for soak.monitor.ResourceMonitor."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from persistence import connect, count_rows, init_db
from soak import ResourceMonitor


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "soak.duckdb")
    init_db(c)
    yield c
    c.close()


def test_sample_persists_row_and_returns_record(conn, tmp_path):
    counter = {"n": 0}

    def get_count() -> int:
        counter["n"] += 1
        return counter["n"] * 2

    mon = ResourceMonitor(
        conn=conn,
        db_path=tmp_path / "soak.duckdb",
        decision_count_fn=get_count,
    )
    s = mon.sample()
    assert s.elapsed_seconds >= 0.0
    assert s.rss_bytes > 0
    assert s.open_fds >= 0
    assert s.n_decisions == 2
    assert count_rows(conn, "soak_resource_samples") == 1


def test_sample_elapsed_increases_monotonically(conn, tmp_path):
    mon = ResourceMonitor(
        conn=conn,
        db_path=tmp_path / "soak.duckdb",
        decision_count_fn=lambda: 0,
    )
    s1 = mon.sample()
    time.sleep(0.02)
    s2 = mon.sample()
    assert s2.elapsed_seconds > s1.elapsed_seconds


def test_sample_uses_injected_now_utc(conn, tmp_path):
    mon = ResourceMonitor(
        conn=conn,
        db_path=tmp_path / "soak.duckdb",
        decision_count_fn=lambda: 0,
        start_ts_utc=datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC),
    )
    future = datetime(2026, 4, 16, 10, 5, 0, tzinfo=UTC)
    s = mon.sample(now_utc=future)
    assert s.ts_utc == future
    assert s.elapsed_seconds == pytest.approx(300.0)


def test_sample_reports_db_size(conn, tmp_path):
    # The mere fact of calling init_db means the duckdb file has some size.
    mon = ResourceMonitor(
        conn=conn,
        db_path=tmp_path / "soak.duckdb",
        decision_count_fn=lambda: 0,
    )
    s = mon.sample()
    assert s.db_size_bytes >= 0
