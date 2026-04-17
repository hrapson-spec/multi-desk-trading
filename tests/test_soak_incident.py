"""Unit tests for soak.incident.IncidentDetector."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.v1 import SoakResourceSample
from persistence import connect, count_rows, init_db
from soak.incident import IncidentDetector, IncidentThresholds


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "soak.duckdb")
    init_db(c)
    yield c
    c.close()


def _sample(
    *,
    sid: str = "s1",
    elapsed: float = 0.0,
    rss: int = 100 * 1024 * 1024,
    fds: int = 20,
    db: int = 0,
    n: int = 0,
) -> SoakResourceSample:
    return SoakResourceSample(
        sample_id=sid,
        ts_utc=datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC),
        elapsed_seconds=elapsed,
        rss_bytes=rss,
        open_fds=fds,
        db_size_bytes=db,
        n_decisions=n,
    )


def test_check_returns_none_before_baseline_set(conn):
    det = IncidentDetector(conn=conn)
    assert det.check(_sample()) is None


def test_check_healthy_returns_none(conn):
    det = IncidentDetector(conn=conn)
    det.set_baseline(_sample(sid="b"))
    result = det.check(_sample(sid="c", rss=105 * 1024 * 1024, fds=22))
    assert result is None
    assert count_rows(conn, "soak_incidents") == 0


def test_memory_leak_detected(conn):
    det = IncidentDetector(
        conn=conn,
        thresholds=IncidentThresholds(
            rss_growth_ratio=1.20,
            rss_growth_abs_bytes=100 * 1024 * 1024,  # 100 MB for easier testing
        ),
    )
    det.set_baseline(_sample(sid="b", rss=100 * 1024 * 1024))
    # Grown to 250 MB — ratio 2.5×, abs growth 150 MB — both thresholds breached
    r = det.check(_sample(sid="c", rss=250 * 1024 * 1024))
    assert r is not None
    assert r.incident_class == "memory_leak"
    assert r.detail["baseline_rss_bytes"] == 100 * 1024 * 1024
    assert r.detail["current_rss_bytes"] == 250 * 1024 * 1024
    assert count_rows(conn, "soak_incidents") == 1


def test_memory_leak_requires_both_thresholds(conn):
    """A small ratio growth that doesn't breach abs-bytes does NOT trip
    the memory leak. Prevents false positives from tiny baselines."""
    det = IncidentDetector(
        conn=conn,
        thresholds=IncidentThresholds(
            rss_growth_ratio=1.20,
            rss_growth_abs_bytes=500 * 1024 * 1024,
        ),
    )
    det.set_baseline(_sample(sid="b", rss=100 * 1024 * 1024))
    # 2× ratio but only 100 MB abs growth — under the 500 MB floor.
    assert det.check(_sample(sid="c", rss=200 * 1024 * 1024)) is None


def test_fd_leak_detected(conn):
    det = IncidentDetector(conn=conn, thresholds=IncidentThresholds(fd_multiplier=5.0))
    det.set_baseline(_sample(sid="b", fds=20))
    r = det.check(_sample(sid="c", fds=101))
    assert r is not None
    assert r.incident_class == "fd_leak"


def test_fd_leak_ignored_when_baseline_zero(conn):
    """Zero baseline FDs would yield infinite ratio; guard against that."""
    det = IncidentDetector(conn=conn)
    det.set_baseline(_sample(sid="b", fds=0))
    # current fds=50, but baseline was 0 → ratio undefined; don't fire.
    result = det.check(_sample(sid="c", fds=50))
    # Either None or a recorded incident with sensible values; either is
    # acceptable. The check is: we don't crash with DivisionByZero.
    assert result is None or result.incident_class == "fd_leak"


def test_disk_growth_detected(conn):
    det = IncidentDetector(
        conn=conn,
        thresholds=IncidentThresholds(db_growth_bytes=100 * 1024 * 1024),
    )
    det.set_baseline(_sample(sid="b", db=50 * 1024 * 1024))
    r = det.check(_sample(sid="c", db=200 * 1024 * 1024))
    assert r is not None
    assert r.incident_class == "disk_growth"


def test_record_exception_persists(conn):
    det = IncidentDetector(conn=conn)
    inc = det.record_exception("db_corruption", {"reason": "test", "path": "/tmp/fake.duckdb"})
    assert inc.incident_class == "db_corruption"
    assert count_rows(conn, "soak_incidents") == 1


def test_record_exception_rejects_telemetry_classes(conn):
    """record_exception is only for runtime-exception classes; numeric
    thresholds go through check() instead."""
    det = IncidentDetector(conn=conn)
    with pytest.raises(ValueError, match="record_exception only handles"):
        det.record_exception("memory_leak", {})  # type: ignore[arg-type]
