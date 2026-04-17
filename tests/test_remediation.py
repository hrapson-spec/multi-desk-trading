"""Tests for research_loop.remediation + gate_failure handler v0.2."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import ResearchLoopEvent
from controller import seed_cold_start
from persistence import connect, get_latest_signal_weights, init_db
from research_loop import (
    HARMFUL_FAILURE_PREFIX,
    RETIRE_ARTEFACT_PREFIX,
    gate_failure_handler,
    is_harmful,
    retire_desk_for_regime,
)

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "remediation.duckdb")
    init_db(c)
    yield c
    c.close()


# ---------------------------------------------------------------------------
# retire_desk_for_regime
# ---------------------------------------------------------------------------


def test_retire_writes_zero_weight(conn):
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE), ("supply", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=NOW,
        default_cold_start_limit=1.0,
    )
    # Pre-retire: uniform weights 0.5 each.
    before = get_latest_signal_weights(conn, "regime_boot")
    w_map_before = {r["desk_name"]: r["weight"] for r in before}
    assert w_map_before["supply"] == pytest.approx(0.5)

    retire_ts = NOW.replace(minute=5)
    sw = retire_desk_for_regime(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="harmful:kronos_style_sign_flip",
        now_utc=retire_ts,
    )
    assert sw.weight == 0.0
    assert sw.validation_artefact.startswith(RETIRE_ARTEFACT_PREFIX)

    after = get_latest_signal_weights(conn, "regime_boot")
    w_map_after = {r["desk_name"]: r["weight"] for r in after}
    assert w_map_after["supply"] == pytest.approx(0.0)
    # Other desk unchanged.
    assert w_map_after["storage_curve"] == pytest.approx(0.5)


def test_retire_rejects_naive_timestamp(conn):
    with pytest.raises(ValueError, match="timezone-aware"):
        retire_desk_for_regime(
            conn,
            regime_id="regime_boot",
            desk_name="supply",
            target_variable=WTI_FRONT_MONTH_CLOSE,
            reason="harmful:test",
            now_utc=datetime(2026, 4, 16, 10, 0, 0),
        )


def test_retire_is_idempotent_under_tie_break(conn):
    """Multiple retire writes converge on weight=0 due to Controller's
    (promotion_ts_utc DESC, weight_id DESC) read order."""
    seed_cold_start(
        conn,
        desks=[("supply", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=NOW,
        default_cold_start_limit=1.0,
    )
    retire_ts = NOW.replace(minute=5)
    retire_desk_for_regime(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="harmful:first",
        now_utc=retire_ts,
    )
    retire_desk_for_regime(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="harmful:second",
        now_utc=retire_ts.replace(minute=10),
    )
    after = get_latest_signal_weights(conn, "regime_boot")
    w_map = {r["desk_name"]: r["weight"] for r in after}
    assert w_map["supply"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# is_harmful helper
# ---------------------------------------------------------------------------


def test_is_harmful_prefix_match():
    assert is_harmful("harmful:sign_flip")
    assert is_harmful("harmful:rmse_above_baseline")
    assert not is_harmful("sign_flip")
    assert not is_harmful("rmse_above_baseline")
    assert not is_harmful("")


def test_harmful_prefix_constant_is_stable():
    """The prefix is part of the public handler payload contract —
    lock the constant to prevent silent drift."""
    assert HARMFUL_FAILURE_PREFIX == "harmful:"


# ---------------------------------------------------------------------------
# gate_failure_handler v0.2
# ---------------------------------------------------------------------------


def test_gate_failure_non_harmful_still_logs(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="gate_failure",
        triggered_at_utc=NOW,
        priority=0,
        payload={
            "desk": "storage_curve",
            "gate": "skill",
            "metric": 0.05,
            "failure_mode": "rmse_above_baseline",
        },
    )
    result = gate_failure_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["handler"] == "gate_failure_v0.2"
    assert data["action"] == "logged_pending_rca"
    assert data["retire_detail"] is None
    # No SignalWeight writes happened
    rows = conn.execute("SELECT count(*) FROM signal_weights").fetchone()
    assert rows[0] == 0


def test_gate_failure_harmful_auto_retires(conn):
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=NOW,
        default_cold_start_limit=1.0,
    )
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="gate_failure",
        triggered_at_utc=NOW.replace(minute=5),
        priority=0,
        payload={
            "desk": "supply",
            "gate": "sign_preservation",
            "metric": -0.3,
            "failure_mode": "harmful:dev_test_sign_flip",
            "regime_id": "regime_boot",
            "target_variable": WTI_FRONT_MONTH_CLOSE,
        },
    )
    result = gate_failure_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["action"] == "retired"
    assert data["retire_detail"]["regime_id"] == "regime_boot"
    assert data["retire_detail"]["validation_artefact"].startswith(RETIRE_ARTEFACT_PREFIX)

    # The weight matrix now has supply at 0.0
    rows = get_latest_signal_weights(conn, "regime_boot")
    w_map = {r["desk_name"]: r["weight"] for r in rows}
    assert w_map["supply"] == pytest.approx(0.0)
    assert w_map["storage_curve"] == pytest.approx(0.5)


def test_gate_failure_harmful_missing_context_is_fail_safe(conn):
    """Harmful failure_mode but missing regime_id / target_variable: log
    that retire is required but don't destructively mutate state."""
    seed_cold_start(
        conn,
        desks=[("supply", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=NOW,
        default_cold_start_limit=1.0,
    )
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="gate_failure",
        triggered_at_utc=NOW,
        priority=0,
        payload={
            "desk": "supply",
            "gate": "skill",
            "metric": 0.2,
            "failure_mode": "harmful:lodo_negative",
            # regime_id and target_variable intentionally missing
        },
    )
    result = gate_failure_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["action"] == "harmful_but_missing_retire_payload"
    assert "missing" in data["retire_detail"]

    # Supply still at 1.0 (only desk, so weight=1/1=1)
    rows = get_latest_signal_weights(conn, "regime_boot")
    assert rows[0]["weight"] == pytest.approx(1.0)


def test_gate_failure_handler_rejects_wrong_event_type(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="periodic_weekly",
        triggered_at_utc=NOW,
        priority=0,
        payload={},
    )
    with pytest.raises(ValueError, match="wrong event"):
        gate_failure_handler(conn, event)


def test_gate_failure_missing_payload_returns_error_artefact(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="gate_failure",
        triggered_at_utc=NOW,
        priority=0,
        payload={"desk": "x", "gate": "skill"},  # missing metric + failure_mode
    )
    result = gate_failure_handler(conn, event)
    data = json.loads(result.artefact)
    assert "error" in data
