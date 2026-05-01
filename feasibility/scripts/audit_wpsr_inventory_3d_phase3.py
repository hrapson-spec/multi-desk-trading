"""Phase 3 audit orchestration for WPSR inventory surprise -> WTI 3d sign.

Pre-registered at feasibility/preregs/2026-04-29-wpsr_inventory_wti_3d.yaml.
Audit-only — does NOT register the candidate as a v1/v2 desk.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from feasibility.candidates.wpsr_inventory_3d.classical import (
    REQUIRED_WPSR_SERIES,
    WPSR_FEATURE_COLUMNS,
    WPSRInventoryLogisticModel,
    build_wpsr_inventory_features,
)
from feasibility.tractability_v1 import (
    DEFAULT_PIT_ROOT,
    DEFAULT_WTI_PATHS,
    POST_2020_START,
    WPSR_FAMILY,
    TargetDef,
    TargetObservation,
    build_target_observations,
    kept_decision_ts,
    load_family_decision_events,
    load_target_prices,
)

HORIZON_DAYS = 3
PURGE_DAYS = 3
EMBARGO_DAYS = 3
WARMUP_WEEKS = 52
REFIT_MONTHS = 1

REPO_ROOT = Path(__file__).resolve().parents[2]
RESIDUALS_CSV = REPO_ROOT / "feasibility" / "outputs" / "wpsr_inventory_3d_residuals.csv"
PHASE3_MANIFEST = (
    REPO_ROOT / "feasibility" / "outputs" / "tractability_v1_3d_phase3_audit_wpsr_inventory.json"
)
PHASE3_REPORT = (
    REPO_ROOT / "feasibility" / "reports" / "terminal_2026-04-29_phase3_audit_wpsr_inventory.md"
)


@dataclass(frozen=True)
class WalkForwardAudit:
    residuals: pd.Series
    model_accuracy: float | None
    zero_return_baseline_accuracy: float | None
    majority_baseline_accuracy: float | None
    directional_accuracy_gain_pp: float | None
    scored_events: int


def _utc_timestamp(value: object) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")


def load_wpsr_panel(
    pit_root: Path,
    *,
    series: tuple[str, ...] = REQUIRED_WPSR_SERIES,
) -> pd.DataFrame:
    """Load a release-time WPSR panel from the PIT manifest."""
    db_path = pit_root / "pit.duckdb"
    if not db_path.exists():
        raise FileNotFoundError(f"PIT manifest missing: {db_path}")

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        placeholders = ",".join("?" for _ in series)
        rows = conn.execute(
            f"""
            SELECT series, usable_after_ts, parquet_path
            FROM pit_manifest
            WHERE source IN ('eia', 'eia_wpsr')
              AND dataset = 'wpsr'
              AND series IN ({placeholders})
            ORDER BY usable_after_ts ASC
            """,
            list(series),
        ).fetchall()
    finally:
        conn.close()

    records: list[tuple[pd.Timestamp, str, float]] = []
    for series_name, usable_after_ts, parquet_path in rows:
        full_path = pit_root / parquet_path
        if not full_path.exists():
            continue
        frame = pd.read_parquet(full_path)
        if "value" not in frame.columns or frame.empty:
            continue
        value = pd.to_numeric(frame["value"], errors="coerce").iloc[0]
        if pd.isna(value):
            continue
        records.append((_utc_timestamp(usable_after_ts), str(series_name), float(value)))

    if not records:
        raise ValueError("no usable WPSR PIT rows found")

    panel = (
        pd.DataFrame(records, columns=["release_ts", "series", "value"])
        .pivot_table(index="release_ts", columns="series", values="value", aggfunc="last")
        .sort_index()
    )
    return panel.dropna(subset=list(series), how="any")


def anchor_release_features_to_target_prices(
    release_features: pd.DataFrame,
    release_ts: list[pd.Timestamp],
    prices: pd.Series,
) -> pd.DataFrame:
    """Index release-time WPSR features by the target price anchor timestamp."""
    price_index = prices.index
    rows: list[pd.Series] = []
    for release_time in release_ts:
        if release_time not in release_features.index:
            continue
        pos = int(price_index.searchsorted(release_time, side="left"))
        if pos >= len(price_index):
            continue
        anchor_ts = pd.Timestamp(price_index[pos]).tz_convert("UTC")
        row = release_features.loc[release_time].copy()
        row.name = anchor_ts
        rows.append(row)

    if not rows:
        return pd.DataFrame(columns=release_features.columns, dtype=float)

    anchored = pd.DataFrame(rows).sort_index()
    return anchored[~anchored.index.duplicated(keep="last")]


def _compute_wti_5d_lagged_return(
    decision_ts: pd.Timestamp,
    prices: pd.Series,
) -> float | None:
    idx = prices.index
    pos = int(idx.searchsorted(decision_ts, side="left"))
    if pos >= len(idx):
        pos = len(idx) - 1
    elif idx[pos] > decision_ts and pos > 0:
        pos -= 1
    if pos < 5:
        return None
    p_t = float(prices.iloc[pos])
    p_t5 = float(prices.iloc[pos - 5])
    if p_t <= 0 or p_t5 <= 0:
        return None
    return float(np.log(p_t / p_t5))


def build_event_features_and_labels(
    kept_obs: list[TargetObservation],
    anchored_wpsr_features: pd.DataFrame,
    prices: pd.Series,
) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Build X/y/decision_ts rows for kept WPSR target observations."""
    feat_rows: list[list[float]] = []
    label_rows: list[int] = []
    ts_rows: list[pd.Timestamp] = []

    for obs in kept_obs:
        if obs.decision_ts not in anchored_wpsr_features.index:
            continue
        lagged = _compute_wti_5d_lagged_return(obs.decision_ts, prices)
        if lagged is None:
            continue
        release_features = anchored_wpsr_features.loc[obs.decision_ts]
        feat_rows.append(
            [
                *[float(release_features[col]) for col in WPSR_FEATURE_COLUMNS],
                lagged,
            ]
        )
        label_rows.append(1 if obs.return_path > 0 else 0)
        ts_rows.append(obs.decision_ts)

    if not feat_rows:
        return np.empty((0, 5), dtype=float), np.empty(0, dtype=int), pd.DatetimeIndex([], tz="UTC")

    return (
        np.array(feat_rows, dtype=float),
        np.array(label_rows, dtype=int),
        pd.DatetimeIndex(ts_rows, tz="UTC"),
    )


def walk_forward_audit(
    feat_mat: np.ndarray,
    label_arr: np.ndarray,
    decision_ts: pd.DatetimeIndex,
    *,
    warmup_weeks: int,
    refit_months: int,
) -> WalkForwardAudit:
    """Rolling-origin walk-forward fit; returns residuals and Gate 1 accuracy."""
    if refit_months != 1:
        raise ValueError("only monthly refit cadence is preregistered for this audit")
    if len(feat_mat) == 0:
        return WalkForwardAudit(pd.Series(dtype=float, name="residual"), None, None, None, None, 0)

    warmup_end = decision_ts[0] + pd.Timedelta(days=warmup_weeks * 7)
    post_warmup_ts = decision_ts[decision_ts >= warmup_end]
    if len(post_warmup_ts) == 0:
        return WalkForwardAudit(pd.Series(dtype=float, name="residual"), None, None, None, None, 0)

    months = sorted({(ts.year, ts.month) for ts in post_warmup_ts}, key=lambda ym: ym)
    residual_values: list[float] = []
    residual_ts: list[pd.Timestamp] = []
    true_signs: list[int] = []
    pred_signs: list[int] = []

    for year, month in months:
        month_start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        month_end = (
            pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
            if month == 12
            else pd.Timestamp(year=year, month=month + 1, day=1, tz="UTC")
        )

        train_mask = decision_ts < month_start
        labels_train = label_arr[train_mask]
        if len(labels_train) < 2 or len(np.unique(labels_train)) < 2:
            continue

        test_mask = (decision_ts >= month_start) & (decision_ts < month_end)
        if not test_mask.any():
            continue

        model = WPSRInventoryLogisticModel()
        model.fit(feat_mat[train_mask], labels_train)

        y_pred_sign = model.predict_sign(feat_mat[test_mask])
        y_true_sign = np.where(label_arr[test_mask] == 1, 1, -1).astype(int)
        batch_residuals = (y_true_sign - y_pred_sign).astype(float)

        residual_values.extend(batch_residuals.tolist())
        residual_ts.extend(decision_ts[test_mask].tolist())
        true_signs.extend(y_true_sign.tolist())
        pred_signs.extend(y_pred_sign.tolist())

    if not residual_values:
        return WalkForwardAudit(pd.Series(dtype=float, name="residual"), None, None, None, None, 0)

    residuals = pd.Series(
        residual_values,
        index=pd.DatetimeIndex(residual_ts, tz="UTC"),
        name="residual",
    ).sort_index()

    true_arr = np.array(true_signs, dtype=int)
    pred_arr = np.array(pred_signs, dtype=int)
    model_accuracy = float(np.mean(true_arr == pred_arr))
    zero_return_baseline_accuracy = float(np.mean(true_arr == -1))
    positive_rate = float(np.mean(true_arr == 1))
    majority_baseline_accuracy = max(positive_rate, 1.0 - positive_rate)
    gain_pp = 100.0 * (model_accuracy - zero_return_baseline_accuracy)

    return WalkForwardAudit(
        residuals=residuals,
        model_accuracy=model_accuracy,
        zero_return_baseline_accuracy=zero_return_baseline_accuracy,
        majority_baseline_accuracy=majority_baseline_accuracy,
        directional_accuracy_gain_pp=gain_pp,
        scored_events=int(len(residuals)),
    )


def write_residuals_csv(residuals: pd.Series, path: Path) -> None:
    """Write residuals to CSV with columns decision_ts (ISO 8601 UTC), residual."""
    frame = pd.DataFrame(
        {
            "decision_ts": residuals.index.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "residual": residuals.values,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


def invoke_harness_residual_mode(residuals_csv: Path, manifest_out: Path) -> dict:
    """Invoke tractability_v1 in Phase 3 residual mode and return the manifest."""
    cmd = [
        sys.executable,
        "-m",
        "feasibility.tractability_v1",
        "--families",
        "wpsr",
        "--horizon-days",
        str(HORIZON_DAYS),
        "--purge-days",
        str(PURGE_DAYS),
        "--embargo-days",
        str(EMBARGO_DAYS),
        "--phase3-residual-mode",
        "--candidate-residuals-csv",
        str(residuals_csv),
        "--output",
        str(manifest_out),
    ]
    subprocess.run(cmd, check=True, cwd=REPO_ROOT)
    return json.loads(manifest_out.read_text())


def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{100.0 * value:.2f}%"


def _fmt_pp(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f} pp"


def write_report(manifest: dict, metrics: WalkForwardAudit, report_path: Path) -> None:
    """Write the WPSR Phase 3 audit verdict report."""
    created_at = manifest.get("created_at_utc", "unknown")
    decision = manifest.get("decision", {})
    n_star = decision.get("min_effective_n", "N/A")
    target_info = manifest.get("targets", {}).get("wti_3d_return_sign", {})
    hac_block = target_info.get("n_hac_or_block_adjusted", {})
    newey_west = hac_block.get("newey_west", {})
    block_bootstrap_info = hac_block.get("block_bootstrap", {})
    hac_n = newey_west.get("point_estimate", "N/A")
    boot_n = block_bootstrap_info.get("point_estimate", "N/A")
    n_after_purge = target_info.get("n_after_purge_embargo", "N/A")

    accuracy_floor_pp = 5.0
    hac_floor = 250
    boot_floor = 250
    accuracy_pass = (
        metrics.directional_accuracy_gain_pp is not None
        and metrics.directional_accuracy_gain_pp >= accuracy_floor_pp
    )
    hac_pass = isinstance(hac_n, int) and hac_n >= hac_floor
    boot_pass = isinstance(boot_n, int) and boot_n >= boot_floor

    reasons: list[str] = []
    if not accuracy_pass:
        reasons.append(
            f"accuracy gain = {_fmt_pp(metrics.directional_accuracy_gain_pp)} < "
            f"{accuracy_floor_pp:.2f} pp"
        )
    if not hac_pass:
        reasons.append(f"HAC N = {hac_n} < {hac_floor}")
    if not boot_pass:
        reasons.append(f"bootstrap N = {boot_n} < {boot_floor}")

    verdict = "ADMISSIBLE" if not reasons else "NON-ADMISSIBLE"
    verdict_detail = (
        "All pre-registered thresholds cleared."
        if not reasons
        else "; ".join(reasons) + ". Candidate does not clear Phase 3 gate."
    )

    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Phase 3 Audit — WPSR Inventory Surprise → WTI 3d Return Sign",
        "",
        "**Pre-reg**: `feasibility/preregs/2026-04-29-wpsr_inventory_wti_3d.yaml`  ",
        f"**Manifest created**: {created_at}  ",
        f"**Report written**: {now_str}  ",
        "**Audit-only**: yes — no v1/v2 desk registration implied.",
        "",
        "---",
        "",
        "## Harness parameters",
        "",
        "| Parameter | Value |",
        "| --- | --- |",
        "| families | wpsr |",
        f"| horizon_days | {HORIZON_DAYS} |",
        f"| purge_days | {PURGE_DAYS} |",
        f"| embargo_days | {EMBARGO_DAYS} |",
        f"| warmup_weeks | {WARMUP_WEEKS} |",
        "| refit_cadence | monthly |",
        "",
        "---",
        "",
        "## Gate 1 — directional skill",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| scored_events | {metrics.scored_events} |",
        f"| model_accuracy | {_fmt_pct(metrics.model_accuracy)} |",
        f"| zero_return_baseline_accuracy | {_fmt_pct(metrics.zero_return_baseline_accuracy)} |",
        f"| majority_baseline_accuracy | {_fmt_pct(metrics.majority_baseline_accuracy)} |",
        "| accuracy_gain_vs_zero_return_baseline | "
        f"{_fmt_pp(metrics.directional_accuracy_gain_pp)} |",
        f"| required_gain | {accuracy_floor_pp:.2f} pp |",
        "",
        "---",
        "",
        "## Gate 2 — effective N waterfall",
        "",
        "| Stage | N |",
        "| --- | ---: |",
        f"| n_after_purge_embargo | {n_after_purge} |",
        f"| HAC effective N (Newey-West, residuals) | {hac_n} |",
        f"| block-bootstrap effective N (residuals) | {boot_n} |",
        f"| n_star (overall, harness decision) | {n_star} |",
        "",
        "---",
        "",
        "## Phase 3 verdict",
        "",
        f"**{verdict}**",
        "",
        verdict_detail,
        "",
        "---",
        "",
        "## Harness decision block",
        "",
        "```json",
        json.dumps(decision, indent=2),
        "```",
        "",
        "---",
        "",
        "*Audit-only report. Does not constitute a promotion recommendation.*",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-root", type=Path, default=DEFAULT_PIT_ROOT)
    parser.add_argument("--skip-harness", action="store_true")
    args = parser.parse_args(argv)

    wpsr_events = load_family_decision_events(args.pit_root, WPSR_FAMILY)
    wti_path = next((p for p in DEFAULT_WTI_PATHS if p.exists()), DEFAULT_WTI_PATHS[0])
    target_def = TargetDef(
        name="wti_3d_return_sign",
        price_path=wti_path,
        horizon_days=HORIZON_DAYS,
        metric="return_sign",
        forbidden_uses=("executable_futures_replay",),
    )
    prices, _ = load_target_prices(target_def)

    obs = build_target_observations([wpsr_events], prices, horizon_days=HORIZON_DAYS)
    obs_post = [o for o in obs if o.decision_ts >= POST_2020_START]
    kept_ts = kept_decision_ts(
        [o.decision_ts for o in obs_post],
        purge_days=PURGE_DAYS,
        embargo_days=EMBARGO_DAYS,
    )
    kept_set = set(kept_ts)
    kept_obs = [o for o in obs_post if o.decision_ts in kept_set]

    print(
        f"Events: {len(obs)} total, {len(obs_post)} post-2020, "
        f"{len(kept_obs)} after purge/embargo ({PURGE_DAYS}d/{EMBARGO_DAYS}d)"
    )

    panel = load_wpsr_panel(args.pit_root)
    release_features = build_wpsr_inventory_features(panel)
    anchored_features = anchor_release_features_to_target_prices(
        release_features,
        wpsr_events.decision_ts,
        prices,
    )

    feat_mat, label_arr, decision_ts = build_event_features_and_labels(
        kept_obs,
        anchored_features,
        prices,
    )
    n_dropped = len(kept_obs) - feat_mat.shape[0]
    print(
        f"Feature matrix: {feat_mat.shape[0]} rows "
        f"(dropped {n_dropped} for missing features or lagged return)"
    )

    audit = walk_forward_audit(
        feat_mat,
        label_arr,
        decision_ts,
        warmup_weeks=WARMUP_WEEKS,
        refit_months=REFIT_MONTHS,
    )
    print(
        f"Walk-forward residuals: {len(audit.residuals)} events; "
        f"accuracy gain vs zero baseline: {_fmt_pp(audit.directional_accuracy_gain_pp)}"
    )

    write_residuals_csv(audit.residuals, RESIDUALS_CSV)
    print(f"Wrote {len(audit.residuals)} residuals to {RESIDUALS_CSV}")

    if args.skip_harness:
        print("Skipping harness invocation per --skip-harness")
        return 0

    manifest = invoke_harness_residual_mode(RESIDUALS_CSV, PHASE3_MANIFEST)
    print(f"Phase 3 manifest: {PHASE3_MANIFEST}")
    print(json.dumps(manifest["decision"], indent=2))

    write_report(manifest, audit, PHASE3_REPORT)
    print(f"Phase 3 report: {PHASE3_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
