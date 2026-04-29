"""Forward holdout operations for the locked WTI lag 1d candidate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from feasibility.candidates.wti_lag_1d.classical import (
    WTILag1DLogisticModel,
)
from feasibility.scripts.audit_wti_lag_1d_phase3 import (
    EMBARGO_DAYS,
    FAMILY_NAMES,
    HORIZON_DAYS,
    MIN_TRAIN_EVENTS,
    PURGE_DAYS,
    _select_kept_observations,
    build_event_features_and_labels,
)
from feasibility.scripts.lock_wti_lag_1d import FORWARD_ROOT, LOCK_JSON
from feasibility.tractability_v1 import (
    DEFAULT_FAMILY_REGISTRY,
    DEFAULT_PIT_ROOT,
    DEFAULT_WTI_PATHS,
    POST_2020_START,
    TargetDef,
    build_target_observations,
    kept_decision_ts,
    load_family_decision_events,
    load_target_prices,
)
from v2.ingest import (
    eia_psm_calendar,
    eia_steo_calendar,
    fomc_calendar,
    gpr_calendar,
    opec_ministerial_calendar,
)

NY = ZoneInfo("America/New_York")
VIENNA = ZoneInfo("Europe/Vienna")
WPSR_RELEASE_TIME_ET = time(10, 30)
WPSR_LATENCY_GUARD_MINUTES = 5

REPO_ROOT = Path(__file__).resolve().parents[2]
QUEUE_CSV = FORWARD_ROOT / "event_queue.csv"
FORECASTS_JSONL = FORWARD_ROOT / "forecasts.jsonl"
OUTCOMES_CSV = FORWARD_ROOT / "outcomes.csv"
MONITOR_REPORT = FORWARD_ROOT / "monitor_report.md"
FORECAST_CHAIN_JSONL = FORWARD_ROOT / "forecast_chain.jsonl"
FORWARD_BASELINE_REPORT = FORWARD_ROOT / "forward_baseline_report.md"
FORECAST_CHAIN_SCHEMA_VERSION = "forecast_chain.v1"
MAX_SCORING_LAG = timedelta(hours=6)
MAX_FEATURE_PRICE_AGE_DAYS = 4


@dataclass(frozen=True)
class QueueEvent:
    event_id: str
    family: str
    event_type: str
    decision_ts: pd.Timestamp
    source_method: str


class LockIntegrityError(RuntimeError):
    """Raised when a forward scorer sees drift from the frozen lock files."""


class ForecastLedgerError(RuntimeError):
    """Raised when the append-only forecast ledger chain is invalid."""


def _utc_ts(value: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _event_id(family: str, event_type: str, decision_ts: pd.Timestamp) -> str:
    raw = f"{family}|{event_type}|{decision_ts.isoformat()}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _queue_event(
    family: str,
    event_type: str,
    decision_ts: datetime | pd.Timestamp,
    source_method: str,
) -> QueueEvent:
    ts = _utc_ts(decision_ts)
    return QueueEvent(
        event_id=_event_id(family, event_type, ts),
        family=family,
        event_type=event_type,
        decision_ts=ts,
        source_method=source_method,
    )


def _wpsr_release_ts_utc(d: date) -> datetime:
    return datetime.combine(d, WPSR_RELEASE_TIME_ET, tzinfo=NY).astimezone(UTC)


def _future_wpsr_events(since: date, until: date) -> list[QueueEvent]:
    cur = since + timedelta(days=(2 - since.weekday()) % 7)
    out: list[QueueEvent] = []
    while cur <= until:
        release_ts = _wpsr_release_ts_utc(cur)
        out.append(
            _queue_event(
                "wpsr",
                "weekly_release_rule_v1",
                release_ts + timedelta(minutes=WPSR_LATENCY_GUARD_MINUTES),
                "wednesday_1030_et_rule_plus_5m_guard",
            )
        )
        cur += timedelta(days=7)
    return out


def _opec_release_ts_utc(d: date) -> datetime:
    return datetime.combine(
        d, opec_ministerial_calendar.RELEASE_TIME_CET, tzinfo=VIENNA
    ).astimezone(UTC)


def build_queue(
    *,
    start_ts: pd.Timestamp,
    days: int = 120,
) -> pd.DataFrame:
    """Build a deterministic forward event queue after the lock timestamp."""
    start_date = start_ts.date()
    until = start_date + timedelta(days=days)
    events: list[QueueEvent] = []
    events.extend(_future_wpsr_events(start_date, until))
    events.extend(
        _queue_event(
            "steo",
            "steo_release",
            ev.usable_after_ts_utc,
            "second_tuesday_rule_v1",
        )
        for ev in eia_steo_calendar.all_events(since=start_date, until=until)
    )
    events.extend(
        _queue_event(
            "psm",
            "psm_release",
            ev.usable_after_ts_utc,
            "last_friday_rule_v1",
        )
        for ev in eia_psm_calendar.all_events(since=start_date, until=until)
    )
    events.extend(
        _queue_event(
            "gpr",
            "gpr_weekly_release",
            ev.usable_after_ts_utc,
            "weekly_friday_rule_v1",
        )
        for ev in gpr_calendar.all_events(since=start_date, until=until)
    )
    events.extend(
        _queue_event(
            "fomc",
            ev.event_type,
            (
                datetime.combine(
                    ev.event_date, fomc_calendar.ANNOUNCEMENT_TIME_ET, tzinfo=NY
                ).astimezone(UTC)
                + timedelta(minutes=fomc_calendar.LATENCY_GUARD_MINUTES)
            ),
            "encoded_fomc_calendar_v1",
        )
        for ev in fomc_calendar.all_events(since=start_date, until=until)
    )
    events.extend(
        _queue_event(
            "opec_ministerial",
            ev.event_type,
            _opec_release_ts_utc(ev.event_date)
            + timedelta(minutes=opec_ministerial_calendar.LATENCY_GUARD_MINUTES),
            "curated_opec_calendar_v1",
        )
        for ev in opec_ministerial_calendar.all_events(since=start_date, until=until)
    )

    events = [event for event in events if event.decision_ts > start_ts]
    unique = {(e.family, e.event_type, e.decision_ts): e for e in events}
    rows = [
        {
            "event_id": e.event_id,
            "family": e.family,
            "event_type": e.event_type,
            "decision_ts": e.decision_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "status": "pending",
            "source_method": e.source_method,
            "target_horizon_days": HORIZON_DAYS,
            "purge_days": PURGE_DAYS,
            "embargo_days": EMBARGO_DAYS,
        }
        for e in sorted(unique.values(), key=lambda event: event.decision_ts)
    ]
    return pd.DataFrame(rows)


def _load_lock() -> dict[str, Any]:
    if not LOCK_JSON.exists():
        raise FileNotFoundError(f"forward lock missing: {LOCK_JSON}")
    return json.loads(LOCK_JSON.read_text())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_lock_integrity(
    lock: dict[str, Any] | None = None,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Verify every file frozen in lock.json still matches its SHA256 and size."""
    lock_payload = lock if lock is not None else _load_lock()
    locked_files = lock_payload.get("locked_files", {})
    missing: list[str] = []
    mismatched: list[dict[str, Any]] = []

    for rel_path, expected in locked_files.items():
        path = repo_root / rel_path
        if not path.exists():
            missing.append(rel_path)
            continue
        actual_sha = _sha256_file(path)
        actual_bytes = path.stat().st_size
        expected_sha = expected.get("sha256")
        expected_bytes = expected.get("bytes")
        if actual_sha != expected_sha or actual_bytes != expected_bytes:
            mismatched.append(
                {
                    "path": rel_path,
                    "expected_sha256": expected_sha,
                    "actual_sha256": actual_sha,
                    "expected_bytes": expected_bytes,
                    "actual_bytes": actual_bytes,
                }
            )

    if missing or mismatched:
        detail = {"missing": missing, "mismatched": mismatched}
        raise LockIntegrityError(
            "forward lock integrity check failed: " + json.dumps(detail, sort_keys=True)
        )

    return {
        "status": "ok",
        "lock_id": lock_payload.get("lock_id"),
        "checked_files": len(locked_files),
    }


def write_queue(days: int = 120) -> pd.DataFrame:
    lock = _load_lock()
    start_ts = _utc_ts(pd.Timestamp(lock["locked_at_utc"]))
    queue = build_queue(start_ts=start_ts, days=days)
    FORWARD_ROOT.mkdir(parents=True, exist_ok=True)
    queue.to_csv(QUEUE_CSV, index=False)
    return queue


def _target_def() -> TargetDef:
    wti_path = next((p for p in DEFAULT_WTI_PATHS if p.exists()), DEFAULT_WTI_PATHS[0])
    return TargetDef(
        name="wti_1d_return_sign",
        price_path=wti_path,
        horizon_days=HORIZON_DAYS,
        metric="return_sign",
        forbidden_uses=("executable_futures_replay",),
    )


def _training_frame(prices: pd.Series, as_of_ts: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
    family_events = [
        load_family_decision_events(DEFAULT_PIT_ROOT, DEFAULT_FAMILY_REGISTRY[name])
        for name in FAMILY_NAMES
    ]
    obs = build_target_observations(family_events, prices, horizon_days=HORIZON_DAYS)
    obs_post = [o for o in obs if POST_2020_START <= o.decision_ts < as_of_ts]
    kept_ts = kept_decision_ts(
        [o.decision_ts for o in obs_post],
        purge_days=PURGE_DAYS,
        embargo_days=PURGE_DAYS,
    )
    kept_obs = _select_kept_observations(obs_post, kept_ts)
    feat_mat, label_arr, _ = build_event_features_and_labels(kept_obs, prices)
    return feat_mat, label_arr


def _fit_forward_model(
    prices: pd.Series, as_of_ts: pd.Timestamp
) -> tuple[WTILag1DLogisticModel, np.ndarray, np.ndarray, int]:
    x_train, y_train = _training_frame(prices, as_of_ts)
    if len(x_train) < MIN_TRAIN_EVENTS or len(np.unique(y_train)) < 2:
        raise RuntimeError(f"insufficient training rows before {as_of_ts}: {len(x_train)} rows")
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std[std == 0.0] = 1.0
    model = WTILag1DLogisticModel()
    model.fit((x_train - mean) / std, y_train)
    return model, mean, std, int(len(x_train))


def _existing_forecast_ids() -> set[str]:
    if not FORECASTS_JSONL.exists():
        return set()
    ids: set[str] = set()
    with FORECASTS_JSONL.open() as fh:
        for line in fh:
            if line.strip():
                ids.add(json.loads(line)["event_id"])
    return ids


def _forecast_lines() -> list[str]:
    if not FORECASTS_JSONL.exists():
        return []
    return [line for line in FORECASTS_JSONL.read_text().splitlines() if line.strip()]


def _chain_lines() -> list[str]:
    if not FORECAST_CHAIN_JSONL.exists():
        return []
    return [line for line in FORECAST_CHAIN_JSONL.read_text().splitlines() if line.strip()]


def _chain_entry(
    *,
    sequence: int,
    forecast: dict[str, Any],
    forecast_line: str,
    previous_chain_hash: str,
) -> dict[str, Any]:
    payload = {
        "schema_version": FORECAST_CHAIN_SCHEMA_VERSION,
        "sequence": sequence,
        "event_id": forecast["event_id"],
        "lock_id": forecast["lock_id"],
        "forecast_sha256": _sha256_text(forecast_line),
        "previous_chain_hash": previous_chain_hash,
    }
    payload["chain_hash"] = _sha256_text(_canonical_json(payload))
    return payload


def _build_forecast_chain_entries(forecast_lines: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    previous = "GENESIS"
    for sequence, line in enumerate(forecast_lines, start=1):
        forecast = json.loads(line)
        entry = _chain_entry(
            sequence=sequence,
            forecast=forecast,
            forecast_line=line,
            previous_chain_hash=previous,
        )
        entries.append(entry)
        previous = str(entry["chain_hash"])
    return entries


def _write_forecast_chain(entries: list[dict[str, Any]]) -> None:
    FORECAST_CHAIN_JSONL.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(_canonical_json(entry) + "\n" for entry in entries)
    FORECAST_CHAIN_JSONL.write_text(text)


def verify_forecast_chain(*, bootstrap_if_missing: bool = False) -> dict[str, Any]:
    """Verify forecasts.jsonl is protected by an append-only hash chain."""
    forecast_lines = _forecast_lines()
    chain_lines = _chain_lines()
    if forecast_lines and not chain_lines and bootstrap_if_missing:
        _write_forecast_chain(_build_forecast_chain_entries(forecast_lines))
        chain_lines = _chain_lines()
    if not forecast_lines:
        if chain_lines:
            raise ForecastLedgerError("forecast chain exists but forecasts.jsonl is empty")
        return {"status": "ok", "forecast_count": 0, "last_chain_hash": "GENESIS"}
    if len(forecast_lines) != len(chain_lines):
        raise ForecastLedgerError(
            f"forecast ledger length mismatch: forecasts={len(forecast_lines)}, "
            f"chain={len(chain_lines)}"
        )

    previous = "GENESIS"
    event_ids: set[str] = set()
    last_hash = previous
    for sequence, (forecast_line, chain_line) in enumerate(
        zip(forecast_lines, chain_lines, strict=True),
        start=1,
    ):
        forecast = json.loads(forecast_line)
        entry = json.loads(chain_line)
        expected_entry = _chain_entry(
            sequence=sequence,
            forecast=forecast,
            forecast_line=forecast_line,
            previous_chain_hash=previous,
        )
        if entry != expected_entry:
            raise ForecastLedgerError(f"forecast chain mismatch at sequence {sequence}")
        event_id = str(forecast["event_id"])
        if event_id in event_ids:
            raise ForecastLedgerError(f"duplicate forecast event_id in ledger: {event_id}")
        event_ids.add(event_id)
        previous = str(entry["chain_hash"])
        last_hash = previous

    return {
        "status": "ok",
        "forecast_count": len(forecast_lines),
        "last_chain_hash": last_hash,
    }


def _append_forecasts(forecasts: list[dict[str, Any]]) -> None:
    if not forecasts:
        if not FORECASTS_JSONL.exists():
            FORECASTS_JSONL.write_text("")
        verify_forecast_chain(bootstrap_if_missing=True)
        return

    chain_status = verify_forecast_chain(bootstrap_if_missing=True)
    previous = str(chain_status["last_chain_hash"])
    start_sequence = int(chain_status["forecast_count"]) + 1
    forecast_lines = [_canonical_json(forecast) for forecast in forecasts]
    chain_entries: list[dict[str, Any]] = []
    for offset, (forecast, forecast_line) in enumerate(zip(forecasts, forecast_lines, strict=True)):
        entry = _chain_entry(
            sequence=start_sequence + offset,
            forecast=forecast,
            forecast_line=forecast_line,
            previous_chain_hash=previous,
        )
        chain_entries.append(entry)
        previous = str(entry["chain_hash"])

    FORWARD_ROOT.mkdir(parents=True, exist_ok=True)
    with FORECASTS_JSONL.open("a") as fh:
        for line in forecast_lines:
            fh.write(line + "\n")
    with FORECAST_CHAIN_JSONL.open("a") as fh:
        for entry in chain_entries:
            fh.write(_canonical_json(entry) + "\n")
    verify_forecast_chain()


def _feature_with_metadata(
    decision_ts: pd.Timestamp,
    prices: pd.Series,
) -> dict[str, Any] | None:
    """Return strict previous-trading-day feature and its freshness metadata."""
    if prices.empty:
        return None
    idx = prices.index
    ts = _utc_ts(decision_ts)
    day_start = pd.Timestamp(ts.date(), tz="UTC")
    pos = int(idx.searchsorted(day_start, side="left")) - 1
    prior_pos = pos - 1
    if pos < 0 or prior_pos < 0:
        return None
    p_t = float(prices.iloc[pos])
    p_lag = float(prices.iloc[prior_pos])
    if p_t <= 0 or p_lag <= 0:
        return None
    anchor_ts = pd.Timestamp(idx[pos]).tz_convert("UTC")
    prior_anchor_ts = pd.Timestamp(idx[prior_pos]).tz_convert("UTC")
    age_days = int((day_start.date() - anchor_ts.date()).days)
    return {
        "feature_value": float(np.log(p_t / p_lag)),
        "feature_price_anchor_ts": anchor_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_lag_price_anchor_ts": prior_anchor_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "feature_price_age_days": age_days,
        "feature_quality_status": (
            "ok" if age_days <= MAX_FEATURE_PRICE_AGE_DAYS else "stale_feature_price"
        ),
    }


def score_due_events(as_of_ts: pd.Timestamp | None = None) -> list[dict[str, Any]]:
    lock_integrity = verify_lock_integrity()
    verify_forecast_chain(bootstrap_if_missing=True)
    as_of = _utc_ts(as_of_ts or datetime.now(UTC))
    if not QUEUE_CSV.exists():
        write_queue()
    queue = pd.read_csv(QUEUE_CSV)
    if queue.empty:
        return []

    prices, _ = load_target_prices(_target_def(), DEFAULT_PIT_ROOT)
    model, mean, std, train_rows = _fit_forward_model(prices, as_of)
    lock = _load_lock()
    if lock_integrity.get("lock_id") != lock.get("lock_id"):
        raise LockIntegrityError("lock id changed during forward scoring")
    existing_ids = _existing_forecast_ids()
    forecasts: list[dict[str, Any]] = []

    for row in queue.to_dict("records"):
        event_id = str(row["event_id"])
        decision_ts = _utc_ts(pd.Timestamp(row["decision_ts"]))
        if event_id in existing_ids or decision_ts > as_of:
            continue
        if as_of > decision_ts + MAX_SCORING_LAG:
            continue
        feature_meta = _feature_with_metadata(decision_ts, prices)
        if feature_meta is None or feature_meta["feature_quality_status"] != "ok":
            continue
        feature = float(feature_meta["feature_value"])
        proba = float(model.predict_proba((np.array([[feature]]) - mean) / std)[0])
        forecasts.append(
            {
                "event_id": event_id,
                "lock_id": lock["lock_id"],
                "scored_at_utc": as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "decision_ts": decision_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "family": row["family"],
                "event_type": row["event_type"],
                "feature_wti_prev_trading_day_1d_log_return": feature,
                "feature_price_anchor_ts": feature_meta["feature_price_anchor_ts"],
                "feature_lag_price_anchor_ts": feature_meta["feature_lag_price_anchor_ts"],
                "feature_price_age_days": feature_meta["feature_price_age_days"],
                "probability_positive": proba,
                "predicted_sign": "positive" if proba > 0.5 else "negative",
                "model_train_rows": train_rows,
            }
        )

    _append_forecasts(forecasts)
    return forecasts


def _load_forecasts() -> list[dict[str, Any]]:
    if not FORECASTS_JSONL.exists():
        return []
    return [json.loads(line) for line in FORECASTS_JSONL.read_text().splitlines() if line]


def _target_outcome(decision_ts: pd.Timestamp, prices: pd.Series) -> dict[str, Any]:
    index = prices.index
    pos = int(index.searchsorted(decision_ts, side="left"))
    if pos >= len(index):
        return {"status": "waiting_for_target_price"}
    end_pos = pos + HORIZON_DAYS
    if end_pos >= len(index):
        return {
            "status": "waiting_for_target_price",
            "target_start_ts": pd.Timestamp(index[pos]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
    ret = float(np.log(float(prices.iloc[end_pos]) / float(prices.iloc[pos])))
    return {
        "status": "resolved",
        "true_sign": "positive" if ret > 0 else "negative",
        "wti_1d_log_return": ret,
        "target_start_ts": pd.Timestamp(index[pos]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_end_ts": pd.Timestamp(index[end_pos]).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_start_price": float(prices.iloc[pos]),
        "target_end_price": float(prices.iloc[end_pos]),
    }


def resolve_outcomes() -> list[dict[str, Any]]:
    prices, price_status = load_target_prices(_target_def(), DEFAULT_PIT_ROOT)
    existing_by_id: dict[str, dict[str, str]] = {}
    if OUTCOMES_CSV.exists() and OUTCOMES_CSV.stat().st_size > 0:
        with OUTCOMES_CSV.open() as fh:
            reader = csv.DictReader(fh)
            existing_by_id = {row["event_id"]: row for row in reader}

    rows: list[dict[str, Any]] = []
    for forecast in _load_forecasts():
        event_id = forecast["event_id"]
        existing = existing_by_id.get(event_id)
        if existing is not None and existing.get("outcome_status") == "resolved":
            rows.append(existing)
            continue
        outcome = _target_outcome(_utc_ts(pd.Timestamp(forecast["decision_ts"])), prices)
        feature_meta = _feature_with_metadata(
            _utc_ts(pd.Timestamp(forecast["decision_ts"])),
            prices,
        ) or {
            "feature_quality_status": "missing_feature_price",
            "feature_price_anchor_ts": "",
            "feature_lag_price_anchor_ts": "",
            "feature_price_age_days": "",
        }
        pred_sign_text = str(forecast["predicted_sign"])
        true_sign_text = str(outcome.get("true_sign", ""))
        correct = int(pred_sign_text == true_sign_text) if outcome["status"] == "resolved" else ""
        rows.append(
            {
                "event_id": event_id,
                "decision_ts": forecast["decision_ts"],
                "family": forecast["family"],
                "predicted_sign": pred_sign_text,
                "feature_quality_status": feature_meta["feature_quality_status"],
                "feature_price_anchor_ts": feature_meta["feature_price_anchor_ts"],
                "feature_lag_price_anchor_ts": feature_meta["feature_lag_price_anchor_ts"],
                "feature_price_age_days": feature_meta["feature_price_age_days"],
                "outcome_status": outcome["status"],
                "true_sign": true_sign_text,
                "correct": correct,
                "wti_1d_log_return": outcome.get("wti_1d_log_return", ""),
                "target_start_ts": outcome.get("target_start_ts", ""),
                "target_end_ts": outcome.get("target_end_ts", ""),
                "target_start_price": outcome.get("target_start_price", ""),
                "target_end_price": outcome.get("target_end_price", ""),
                "resolved_at_utc": (
                    datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                    if outcome["status"] == "resolved"
                    else ""
                ),
                "price_source_metadata": _canonical_json(price_status),
            }
        )

    with OUTCOMES_CSV.open("w", newline="") as fh:
        fieldnames = [
            "event_id",
            "decision_ts",
            "family",
            "predicted_sign",
            "feature_quality_status",
            "feature_price_anchor_ts",
            "feature_lag_price_anchor_ts",
            "feature_price_age_days",
            "outcome_status",
            "true_sign",
            "correct",
            "wti_1d_log_return",
            "target_start_ts",
            "target_end_ts",
            "target_start_price",
            "target_end_price",
            "resolved_at_utc",
            "price_source_metadata",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def _forward_baseline_metrics(outcomes: pd.DataFrame) -> dict[str, Any]:
    if outcomes.empty or "outcome_status" not in outcomes.columns:
        return {"resolved_n": 0}
    resolved = outcomes[outcomes["outcome_status"] == "resolved"]
    if "feature_quality_status" in resolved.columns:
        resolved = resolved[resolved["feature_quality_status"] == "ok"]
    if resolved.empty:
        return {"resolved_n": 0}
    correct = pd.to_numeric(resolved["correct"], errors="coerce")
    true_sign = resolved["true_sign"].astype(str)
    model_accuracy = float(correct.mean())
    zero_accuracy = float((true_sign == "negative").mean())
    positive_rate = float((true_sign == "positive").mean())
    majority_accuracy = max(positive_rate, 1.0 - positive_rate)
    return {
        "resolved_n": int(len(resolved)),
        "model_accuracy": model_accuracy,
        "zero_return_baseline_accuracy": zero_accuracy,
        "majority_baseline_accuracy": majority_accuracy,
        "gain_vs_zero_pp": 100.0 * (model_accuracy - zero_accuracy),
        "gain_vs_majority_pp": 100.0 * (model_accuracy - majority_accuracy),
    }


def write_forward_baseline_report() -> None:
    outcomes = pd.read_csv(OUTCOMES_CSV) if OUTCOMES_CSV.exists() else pd.DataFrame()
    metrics = _forward_baseline_metrics(outcomes)
    resolved_n = metrics["resolved_n"]
    lines = [
        "# WTI Lag 1d Forward Baselines",
        "",
        f"**Updated**: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| resolved_events | {resolved_n} |",
    ]
    if resolved_n:
        lines.extend(
            [
                f"| model_accuracy | {100.0 * metrics['model_accuracy']:.2f}% |",
                "| zero_return_baseline_accuracy | "
                f"{100.0 * metrics['zero_return_baseline_accuracy']:.2f}% |",
                "| majority_baseline_accuracy | "
                f"{100.0 * metrics['majority_baseline_accuracy']:.2f}% |",
                f"| gain_vs_zero_return_baseline | {metrics['gain_vs_zero_pp']:.2f} pp |",
                f"| gain_vs_majority_baseline | {metrics['gain_vs_majority_pp']:.2f} pp |",
            ]
        )
    else:
        lines.append("| status | waiting_for_resolved_forward_outcomes |")
    lines.append("")
    FORWARD_BASELINE_REPORT.write_text("\n".join(lines))


def write_monitor_report() -> None:
    lock = _load_lock()
    try:
        lock_integrity = verify_lock_integrity(lock)
    except LockIntegrityError as exc:
        lock_integrity = {"status": "failed", "detail": str(exc)}
    queue = pd.read_csv(QUEUE_CSV) if QUEUE_CSV.exists() else pd.DataFrame()
    forecasts = _load_forecasts()
    outcomes = pd.read_csv(OUTCOMES_CSV) if OUTCOMES_CSV.exists() else pd.DataFrame()
    baseline_metrics = _forward_baseline_metrics(outcomes)
    stale_feature_forecasts = 0
    if not outcomes.empty and "feature_quality_status" in outcomes.columns:
        stale_feature_forecasts = int((outcomes["feature_quality_status"] != "ok").sum())
    forecasted_ids = {forecast["event_id"] for forecast in forecasts}
    pending_queue = (
        queue[~queue["event_id"].astype(str).isin(forecasted_ids)] if not queue.empty else queue
    )
    next_events = pending_queue.head(10).to_dict("records") if not pending_queue.empty else []
    now = pd.Timestamp(datetime.now(UTC))
    missed_unscored = 0
    if not pending_queue.empty:
        missed_unscored = int(
            (
                pd.to_datetime(pending_queue["decision_ts"], utc=True)
                + pd.Timedelta(MAX_SCORING_LAG)
                < now
            ).sum()
        )
    metrics = lock["phase3_historical_metrics"]
    lines = [
        "# WTI Lag 1d Forward Monitor",
        "",
        f"**Lock id**: `{lock['lock_id']}`  ",
        f"**Updated**: {datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}  ",
        "**Status**: forward holdout initialized; no tuning permitted.  ",
        f"**Lock integrity**: {lock_integrity['status']}  ",
        "",
        "## Counts",
        "",
        "| Item | Count |",
        "| --- | ---: |",
        f"| queued_events | {len(queue)} |",
        f"| forecasts_written | {len(forecasts)} |",
        f"| feature_stale_or_missing_forecasts | {stale_feature_forecasts} |",
        f"| outcomes_resolved | {baseline_metrics['resolved_n']} |",
        f"| missed_unscored_events | {missed_unscored} |",
        "",
        "## Forward Baselines",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| resolved_events | {baseline_metrics['resolved_n']} |",
    ]
    if baseline_metrics["resolved_n"]:
        lines.extend(
            [
                f"| model_accuracy | {100.0 * baseline_metrics['model_accuracy']:.2f}% |",
                f"| gain_vs_zero_return_baseline | {baseline_metrics['gain_vs_zero_pp']:.2f} pp |",
                f"| gain_vs_majority_baseline | {baseline_metrics['gain_vs_majority_pp']:.2f} pp |",
            ]
        )
    lines.extend(
        [
            "",
            "## Historical Lock Metrics",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| HAC effective N | {metrics['hac_effective_n']} |",
            f"| block-bootstrap effective N | {metrics['block_bootstrap_effective_n']} |",
            "| gain_vs_zero_return_baseline | "
            f"{metrics['gain_vs_zero_return_baseline_pp']:.2f} pp |",
            f"| gain_vs_majority_baseline | {metrics['gain_vs_majority_baseline_pp']:.2f} pp |",
            "",
            "## Next Queue Events",
            "",
            "| decision_ts | family | event_type | source_method |",
            "| --- | --- | --- | --- |",
        ]
    )
    for event in next_events:
        lines.append(
            "| {decision_ts} | {family} | {event_type} | {source_method} |".format(**event)
        )
    if not next_events:
        lines.append("| N/A | N/A | N/A | N/A |")
    lines.extend(
        [
            "",
            "## Promotion Guard",
            "",
            (
                "Promotion review remains blocked until at least 60 forward "
                "events are scored and resolved with unchanged files, unchanged "
                "thresholds, and explicit zero-return plus majority-baseline checks."
            ),
            "",
        ]
    )
    MONITOR_REPORT.write_text("\n".join(lines))


def run_all(days: int = 120, as_of_ts: pd.Timestamp | None = None) -> None:
    write_queue(days=days)
    score_due_events(as_of_ts=as_of_ts)
    resolve_outcomes()
    write_forward_baseline_report()
    write_monitor_report()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd")
    q = sub.add_parser("build-queue")
    q.add_argument("--days", type=int, default=120)
    sub.add_parser("score")
    sub.add_parser("resolve")
    sub.add_parser("baselines")
    sub.add_parser("monitor")
    a = sub.add_parser("all")
    a.add_argument("--days", type=int, default=120)
    args = parser.parse_args(argv)

    if args.cmd == "build-queue":
        queue = write_queue(days=args.days)
        print(f"queued_events={len(queue)}")
    elif args.cmd == "score":
        print(f"forecasts_written={len(score_due_events())}")
    elif args.cmd == "resolve":
        print(f"outcomes_resolved={len(resolve_outcomes())}")
    elif args.cmd == "baselines":
        write_forward_baseline_report()
        print(f"baseline_report={FORWARD_BASELINE_REPORT}")
    elif args.cmd == "monitor":
        write_monitor_report()
        print(f"monitor_report={MONITOR_REPORT}")
    else:
        run_all(days=getattr(args, "days", 120))
        print(f"queue={QUEUE_CSV}")
        print(f"forecasts={FORECASTS_JSONL}")
        print(f"outcomes={OUTCOMES_CSV}")
        print(f"chain={FORECAST_CHAIN_JSONL}")
        print(f"monitor={MONITOR_REPORT}")
        print(f"baselines={FORWARD_BASELINE_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
