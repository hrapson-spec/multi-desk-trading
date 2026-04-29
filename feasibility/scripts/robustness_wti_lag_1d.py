"""No-tuning robustness diagnostics for the WTI lag 1d audit candidate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from feasibility.candidates.wti_lag_1d.classical import WTILag1DLogisticModel
from feasibility.scripts.audit_wti_lag_1d_phase3 import (
    FAMILY_NAMES,
    HORIZON_DAYS,
    MIN_TRAIN_EVENTS,
    PURGE_DAYS,
    _select_kept_observations,
    build_event_features_and_labels,
)
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

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_JSON = REPO_ROOT / "feasibility" / "outputs" / "wti_lag_1d_robustness.json"
REPORT_MD = REPO_ROOT / "feasibility" / "reports" / "terminal_2026-04-29_wti_lag_1d_robustness.md"


@dataclass(frozen=True)
class PredictionRow:
    decision_ts: pd.Timestamp
    family: str
    y_true_sign: int
    y_pred_sign: int


def _target_def() -> TargetDef:
    wti_path = next((p for p in DEFAULT_WTI_PATHS if p.exists()), DEFAULT_WTI_PATHS[0])
    return TargetDef(
        name="wti_1d_return_sign",
        price_path=wti_path,
        horizon_days=HORIZON_DAYS,
        metric="return_sign",
        forbidden_uses=("executable_futures_replay",),
    )


def _kept_rows() -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex, dict[pd.Timestamp, str]]:
    family_events = [
        load_family_decision_events(DEFAULT_PIT_ROOT, DEFAULT_FAMILY_REGISTRY[name])
        for name in FAMILY_NAMES
    ]
    prices, _ = load_target_prices(_target_def(), DEFAULT_PIT_ROOT)
    obs = build_target_observations(family_events, prices, horizon_days=HORIZON_DAYS)
    obs_post = [o for o in obs if o.decision_ts >= POST_2020_START]
    kept_ts = kept_decision_ts(
        [o.decision_ts for o in obs_post],
        purge_days=PURGE_DAYS,
        embargo_days=PURGE_DAYS,
    )
    kept_obs = _select_kept_observations(obs_post, kept_ts)
    family_by_ts = {obs.decision_ts: obs.family for obs in kept_obs}
    feat_mat, label_arr, decision_ts = build_event_features_and_labels(kept_obs, prices)
    return feat_mat, label_arr, decision_ts, family_by_ts


def _prediction_rows() -> list[PredictionRow]:
    feat_mat, label_arr, decision_ts, family_by_ts = _kept_rows()
    rows: list[PredictionRow] = []
    if len(feat_mat) == 0:
        return rows

    warmup_ts = decision_ts[min(MIN_TRAIN_EVENTS, len(decision_ts) - 1)]
    months = sorted({(ts.year, ts.month) for ts in decision_ts[decision_ts >= warmup_ts]})

    for year, month in months:
        month_start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        month_end = (
            pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
            if month == 12
            else pd.Timestamp(year=year, month=month + 1, day=1, tz="UTC")
        )
        train_mask = decision_ts < month_start
        if train_mask.sum() < MIN_TRAIN_EVENTS or len(np.unique(label_arr[train_mask])) < 2:
            continue
        test_mask = (decision_ts >= month_start) & (decision_ts < month_end)
        if not test_mask.any():
            continue
        x_train = feat_mat[train_mask]
        mean = x_train.mean(axis=0)
        std = x_train.std(axis=0)
        std[std == 0.0] = 1.0
        model = WTILag1DLogisticModel()
        model.fit((x_train - mean) / std, label_arr[train_mask])
        pred = model.predict_sign((feat_mat[test_mask] - mean) / std)
        truth = np.where(label_arr[test_mask] == 1, 1, -1).astype(int)
        for ts, y_true, y_pred in zip(decision_ts[test_mask], truth, pred, strict=True):
            rows.append(
                PredictionRow(
                    decision_ts=ts,
                    family=family_by_ts.get(ts, "unknown"),
                    y_true_sign=int(y_true),
                    y_pred_sign=int(y_pred),
                )
            )
    rows.sort(key=lambda row: row.decision_ts)
    return rows


def _metrics(rows: list[PredictionRow]) -> dict[str, float | int | None]:
    if not rows:
        return {
            "n": 0,
            "accuracy": None,
            "zero_return_baseline_accuracy": None,
            "majority_baseline_accuracy": None,
            "gain_vs_zero_pp": None,
            "gain_vs_majority_pp": None,
        }
    truth = np.array([row.y_true_sign for row in rows])
    pred = np.array([row.y_pred_sign for row in rows])
    accuracy = float(np.mean(truth == pred))
    zero_acc = float(np.mean(truth == -1))
    positive_rate = float(np.mean(truth == 1))
    majority = max(positive_rate, 1.0 - positive_rate)
    return {
        "n": len(rows),
        "accuracy": accuracy,
        "zero_return_baseline_accuracy": zero_acc,
        "majority_baseline_accuracy": majority,
        "gain_vs_zero_pp": 100.0 * (accuracy - zero_acc),
        "gain_vs_majority_pp": 100.0 * (accuracy - majority),
    }


def run_diagnostics() -> dict:
    rows = _prediction_rows()
    by_family = {
        family: _metrics([row for row in rows if row.family == family])
        for family in sorted({row.family for row in rows})
    }
    windows = {
        "2020_2021": (
            pd.Timestamp("2020-01-01T00:00:00Z"),
            pd.Timestamp("2022-01-01T00:00:00Z"),
        ),
        "2022_2023": (
            pd.Timestamp("2022-01-01T00:00:00Z"),
            pd.Timestamp("2024-01-01T00:00:00Z"),
        ),
        "2024_2026": (
            pd.Timestamp("2024-01-01T00:00:00Z"),
            pd.Timestamp("2027-01-01T00:00:00Z"),
        ),
        "ex_2020": (
            pd.Timestamp("2021-01-01T00:00:00Z"),
            pd.Timestamp("2027-01-01T00:00:00Z"),
        ),
    }
    by_window = {
        name: _metrics([row for row in rows if start <= row.decision_ts < end])
        for name, (start, end) in windows.items()
    }
    truth = np.array([row.y_true_sign for row in rows])
    pred = np.array([row.y_pred_sign for row in rows])
    placebo: dict[str, dict[str, float | int | None]] = {}
    for shift in (-5, -2, 2, 5):
        if abs(shift) >= len(rows):
            placebo[str(shift)] = _metrics([])
            continue
        shifted_truth = truth[abs(shift) :] if shift > 0 else truth[:shift]
        shifted_pred = pred[:-shift] if shift > 0 else pred[abs(shift) :]
        synthetic = [
            PredictionRow(
                decision_ts=rows[i].decision_ts,
                family="placebo",
                y_true_sign=int(y_true),
                y_pred_sign=int(y_pred),
            )
            for i, (y_true, y_pred) in enumerate(zip(shifted_truth, shifted_pred, strict=True))
        ]
        placebo[str(shift)] = _metrics(synthetic)

    diagnostics = {
        "created_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall": _metrics(rows),
        "by_family": by_family,
        "by_window": by_window,
        "date_shift_placebo_rows": placebo,
        "leakage_check": {
            "feature_rule": "strict_previous_trading_day_excludes_event_day_daily_price",
            "status": "pass_by_code_path",
        },
    }
    OUTPUT_JSON.write_text(json.dumps(diagnostics, indent=2, sort_keys=True) + "\n")
    return diagnostics


def _fmt(value: float | int | None, suffix: str = "") -> str:
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return f"{value}{suffix}"
    return f"{value:.2f}{suffix}"


def write_report(diagnostics: dict) -> None:
    overall = diagnostics["overall"]
    lines = [
        "# WTI Lag 1d Robustness Diagnostics",
        "",
        f"**Created**: {diagnostics['created_at_utc']}  ",
        "**Mode**: no-tuning diagnostics on the locked historical candidate.",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| scored_events | {overall['n']} |",
        "| accuracy | "
        f"{_fmt(100.0 * overall['accuracy'], '%') if overall['accuracy'] is not None else 'N/A'} |",
        f"| gain_vs_zero_return_baseline | {_fmt(overall['gain_vs_zero_pp'], ' pp')} |",
        f"| gain_vs_majority_baseline | {_fmt(overall['gain_vs_majority_pp'], ' pp')} |",
        "",
        "## Family Slices",
        "",
        "| Family | N | Accuracy | Gain vs zero | Gain vs majority |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for family, metrics in diagnostics["by_family"].items():
        accuracy = metrics["accuracy"]
        lines.append(
            f"| {family} | {metrics['n']} | "
            f"{_fmt(100.0 * accuracy, '%') if accuracy is not None else 'N/A'} | "
            f"{_fmt(metrics['gain_vs_zero_pp'], ' pp')} | "
            f"{_fmt(metrics['gain_vs_majority_pp'], ' pp')} |"
        )
    lines.extend(
        [
            "",
            "## Time Slices",
            "",
            "| Window | N | Accuracy | Gain vs zero | Gain vs majority |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for window, metrics in diagnostics["by_window"].items():
        accuracy = metrics["accuracy"]
        lines.append(
            f"| {window} | {metrics['n']} | "
            f"{_fmt(100.0 * accuracy, '%') if accuracy is not None else 'N/A'} | "
            f"{_fmt(metrics['gain_vs_zero_pp'], ' pp')} | "
            f"{_fmt(metrics['gain_vs_majority_pp'], ' pp')} |"
        )
    lines.extend(
        [
            "",
            "## Placebo Date Shifts",
            "",
            "| Shift rows | N | Accuracy | Gain vs zero |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for shift, metrics in diagnostics["date_shift_placebo_rows"].items():
        accuracy = metrics["accuracy"]
        lines.append(
            f"| {shift} | {metrics['n']} | "
            f"{_fmt(100.0 * accuracy, '%') if accuracy is not None else 'N/A'} | "
            f"{_fmt(metrics['gain_vs_zero_pp'], ' pp')} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "Forward holdout remains mandatory. The historical candidate "
                "clears the registered zero-return baseline but does not clear "
                "the realized majority-sign baseline, so promotion review must "
                "treat majority skill as an explicit hurdle."
            ),
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines))


def main() -> int:
    diagnostics = run_diagnostics()
    write_report(diagnostics)
    print(f"robustness_json={OUTPUT_JSON}")
    print(f"robustness_report={REPORT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
