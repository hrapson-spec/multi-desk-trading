"""Tests for WTI lag 1d forward-lock helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

import feasibility.scripts.forward_wti_lag_1d as forward
from feasibility.scripts.forward_wti_lag_1d import (
    ForecastLedgerError,
    LockIntegrityError,
    build_queue,
    verify_forecast_chain,
    verify_lock_integrity,
)
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


def test_verify_lock_integrity_passes_for_matching_file(tmp_path) -> None:
    locked = tmp_path / "locked.txt"
    locked.write_text("frozen\n")
    digest = hashlib.sha256(locked.read_bytes()).hexdigest()
    payload = {
        "lock_id": "test-lock",
        "locked_files": {
            "locked.txt": {
                "sha256": digest,
                "bytes": locked.stat().st_size,
            }
        },
    }

    result = verify_lock_integrity(payload, repo_root=tmp_path)

    assert result == {"status": "ok", "lock_id": "test-lock", "checked_files": 1}


def test_verify_lock_integrity_raises_for_hash_mismatch(tmp_path) -> None:
    locked = tmp_path / "locked.txt"
    locked.write_text("frozen\n")
    payload = {
        "lock_id": "test-lock",
        "locked_files": {
            "locked.txt": {
                "sha256": hashlib.sha256(locked.read_bytes()).hexdigest(),
                "bytes": locked.stat().st_size,
            }
        },
    }
    locked.write_text("changed\n")

    with pytest.raises(LockIntegrityError, match="mismatched"):
        verify_lock_integrity(payload, repo_root=tmp_path)


def test_score_due_events_refuses_lock_drift(monkeypatch) -> None:
    def fail_integrity() -> dict:
        raise LockIntegrityError("forward lock integrity check failed")

    monkeypatch.setattr(forward, "verify_lock_integrity", fail_integrity)

    with pytest.raises(LockIntegrityError, match="integrity"):
        forward.score_due_events(pd.Timestamp("2026-04-29T15:00:00Z"))


def test_verify_forecast_chain_bootstraps_and_detects_tampering(
    tmp_path,
    monkeypatch,
) -> None:
    forecasts = tmp_path / "forecasts.jsonl"
    chain = tmp_path / "forecast_chain.jsonl"
    forecast = {
        "event_id": "e1",
        "lock_id": "lock",
        "decision_ts": "2026-04-29T14:35:00Z",
    }
    forecasts.write_text(forward._canonical_json(forecast) + "\n")
    monkeypatch.setattr(forward, "FORECASTS_JSONL", forecasts)
    monkeypatch.setattr(forward, "FORECAST_CHAIN_JSONL", chain)

    result = verify_forecast_chain(bootstrap_if_missing=True)

    assert result["forecast_count"] == 1
    assert chain.exists()

    forecasts.write_text(
        forward._canonical_json({**forecast, "decision_ts": "2026-04-30T14:35:00Z"}) + "\n"
    )
    with pytest.raises(ForecastLedgerError, match="mismatch"):
        verify_forecast_chain()


class _FakeModel:
    def predict_proba(self, _x):
        return np.array([0.6])


def _patch_score_dependencies(monkeypatch, tmp_path, decision_ts: str) -> None:
    queue = tmp_path / "queue.csv"
    forecasts = tmp_path / "forecasts.jsonl"
    chain = tmp_path / "forecast_chain.jsonl"
    queue.write_text(
        "event_id,family,event_type,decision_ts,status,source_method,"
        "target_horizon_days,purge_days,embargo_days\n"
        f"e1,wpsr,weekly_release,{decision_ts},pending,fixture,1,1,1\n"
    )
    monkeypatch.setattr(forward, "FORWARD_ROOT", tmp_path)
    monkeypatch.setattr(forward, "QUEUE_CSV", queue)
    monkeypatch.setattr(forward, "FORECASTS_JSONL", forecasts)
    monkeypatch.setattr(forward, "FORECAST_CHAIN_JSONL", chain)
    monkeypatch.setattr(forward, "verify_lock_integrity", lambda: {"lock_id": "lock"})
    monkeypatch.setattr(forward, "_load_lock", lambda: {"lock_id": "lock"})
    monkeypatch.setattr(
        forward,
        "load_target_prices",
        lambda *_args, **_kwargs: (pd.Series(dtype=float), {}),
    )
    monkeypatch.setattr(
        forward,
        "_fit_forward_model",
        lambda *_args, **_kwargs: (_FakeModel(), np.array([0.0]), np.array([1.0]), 99),
    )
    monkeypatch.setattr(
        forward,
        "_feature_with_metadata",
        lambda *_args, **_kwargs: {
            "feature_value": 0.1,
            "feature_price_anchor_ts": "2026-04-28T00:00:00Z",
            "feature_lag_price_anchor_ts": "2026-04-27T00:00:00Z",
            "feature_price_age_days": 1,
            "feature_quality_status": "ok",
        },
    )


def test_score_due_events_is_idempotent(monkeypatch, tmp_path) -> None:
    _patch_score_dependencies(
        monkeypatch,
        tmp_path,
        decision_ts="2026-04-29T15:00:00Z",
    )

    first = forward.score_due_events(pd.Timestamp("2026-04-29T15:10:00Z"))
    second = forward.score_due_events(pd.Timestamp("2026-04-29T15:20:00Z"))

    assert len(first) == 1
    assert second == []
    assert len(forward.FORECASTS_JSONL.read_text().splitlines()) == 1
    assert verify_forecast_chain()["forecast_count"] == 1


def test_score_due_events_skips_after_scoring_deadline(monkeypatch, tmp_path) -> None:
    _patch_score_dependencies(
        monkeypatch,
        tmp_path,
        decision_ts="2026-04-29T08:00:00Z",
    )

    result = forward.score_due_events(pd.Timestamp("2026-04-29T15:00:01Z"))

    assert result == []
    assert forward.FORECASTS_JSONL.read_text() == ""
    assert verify_forecast_chain()["forecast_count"] == 0


def test_score_due_events_skips_stale_feature_price(monkeypatch, tmp_path) -> None:
    _patch_score_dependencies(
        monkeypatch,
        tmp_path,
        decision_ts="2026-04-29T15:00:00Z",
    )
    monkeypatch.setattr(
        forward,
        "_feature_with_metadata",
        lambda *_args, **_kwargs: {
            "feature_value": 0.1,
            "feature_price_anchor_ts": "2026-04-20T00:00:00Z",
            "feature_lag_price_anchor_ts": "2026-04-17T00:00:00Z",
            "feature_price_age_days": 9,
            "feature_quality_status": "stale_feature_price",
        },
    )

    result = forward.score_due_events(pd.Timestamp("2026-04-29T15:10:00Z"))

    assert result == []
    assert forward.FORECASTS_JSONL.read_text() == ""


def test_target_outcome_reports_waiting_and_resolved_states() -> None:
    prices = pd.Series(
        [100.0, 105.0],
        index=pd.DatetimeIndex(["2026-04-29T00:00:00Z", "2026-04-30T00:00:00Z"]),
    )

    resolved = forward._target_outcome(pd.Timestamp("2026-04-29T00:00:00Z"), prices)
    waiting = forward._target_outcome(pd.Timestamp("2026-04-30T00:00:00Z"), prices)

    assert resolved["status"] == "resolved"
    assert resolved["true_sign"] == "positive"
    assert waiting["status"] == "waiting_for_target_price"


def test_forward_baseline_metrics_compare_zero_and_majority() -> None:
    outcomes = pd.DataFrame(
        {
            "outcome_status": ["resolved", "resolved", "waiting_for_target_price"],
            "correct": [1, 0, ""],
            "true_sign": ["negative", "positive", ""],
        }
    )

    metrics = forward._forward_baseline_metrics(outcomes)

    assert metrics["resolved_n"] == 2
    assert metrics["model_accuracy"] == pytest.approx(0.5)
    assert metrics["zero_return_baseline_accuracy"] == pytest.approx(0.5)
    assert metrics["majority_baseline_accuracy"] == pytest.approx(0.5)
