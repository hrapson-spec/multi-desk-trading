"""Tests for WTI lag 1d forward-lock helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pandas as pd

from feasibility.scripts.forward_wti_lag_1d import build_queue
from feasibility.scripts.lock_wti_lag_1d import build_lock


def test_build_lock_freezes_candidate_identity() -> None:
    payload = build_lock(datetime(2026, 4, 29, 12, 0, tzinfo=UTC))

    assert payload["candidate"]["target_variable"] == "wti_front_1d_return_sign"
    assert payload["candidate"]["horizon_days"] == 1
    assert "lock_id" in payload
    assert payload["phase3_historical_metrics"]["hac_effective_n"] >= 250
    assert any("classical.py" in path for path in payload["locked_files"])
    json.dumps(payload)


def test_build_queue_contains_future_registered_calendar_events() -> None:
    queue = build_queue(start_ts=pd.Timestamp("2026-04-29T12:00:00Z"), days=45)

    assert not queue.empty
    assert set(queue["family"]).issuperset({"wpsr", "gpr", "steo", "psm"})
    assert queue["event_id"].is_unique
    assert (
        pd.to_datetime(queue["decision_ts"], utc=True) > pd.Timestamp("2026-04-29T12:00:00Z")
    ).all()


def test_build_queue_is_deterministic() -> None:
    start = pd.Timestamp("2026-04-29T12:00:00Z")

    left = build_queue(start_ts=start, days=60)
    right = build_queue(start_ts=start, days=60)

    pd.testing.assert_frame_equal(left, right)
