"""Phase 3 audit orchestration for FOMC→WTI 3d feasibility candidate.

Pre-registered at feasibility/preregs/2026-04-29-fomc_wti_3d.yaml.
Audit-only — does NOT register the candidate as a v1/v2 desk.

Requires harness flags --phase3-residual-mode and --candidate-residuals-csv
(delivered in Wave 2 of post-data-plan execution).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from feasibility.candidates.fomc_wti_3d.classical import (
    LogisticRegressionFeasibilityModel,
)
from feasibility.tractability_v1 import (
    DEFAULT_PIT_ROOT,
    DEFAULT_WTI_PATHS,
    POST_2020_START,
    TargetDef,
    TargetObservation,
    _resolve_families,
    build_target_observations,
    kept_decision_ts,
    load_family_decision_events,
    load_target_prices,
)

HORIZON_DAYS = 3
PURGE_DAYS = 3
EMBARGO_DAYS = 3
WARMUP_WEEKS = 52  # per prereg outer_protocol
REFIT_MONTHS = 1   # per prereg outer_protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
RESIDUALS_CSV = REPO_ROOT / "feasibility" / "outputs" / "fomc_3d_residuals.csv"
PHASE3_MANIFEST = (
    REPO_ROOT / "feasibility" / "outputs" / "tractability_v1_3d_phase3_audit_fomc.json"
)
PHASE3_REPORT = REPO_ROOT / "feasibility" / "reports" / "terminal_2026-04-29_phase3_audit_fomc.md"


def _compute_wti_5d_lagged_return(
    decision_ts: pd.Timestamp,
    prices: pd.Series,
) -> float | None:
    """Return log(P[t] / P[t-5]) anchored at decision_ts, or None if unavailable.

    'P[t]' is the price at or just before decision_ts; 'P[t-5]' is 5
    calendar days earlier in the price index (business-day steps via iloc).
    Returns None when fewer than 6 price rows exist before the event.
    """
    idx = prices.index
    pos = int(idx.searchsorted(decision_ts, side="left"))
    # Use the last available price at or before decision_ts.
    if pos >= len(idx):
        pos = len(idx) - 1
    elif idx[pos] > decision_ts and pos > 0:
        pos -= 1
    if pos < 5:
        return None
    p_t = float(prices.iloc[pos])
    p_t5 = float(prices.iloc[pos - 5])
    if p_t5 <= 0 or p_t <= 0:
        return None
    return float(np.log(p_t / p_t5))


def build_event_features_and_labels(
    kept_obs: list[TargetObservation],
    prices: pd.Series,
) -> tuple[np.ndarray, np.ndarray, pd.DatetimeIndex]:
    """Build (X, y, decision_ts) for the kept observation set.

    X columns: [fomc_event_indicator (1 if event family == 'fomc' else 0),
                wti_5d_lagged_return (log return over the 5d before decision_ts)]
    y: binary label — 1 if forward 3d log return > 0, else 0
    decision_ts: UTC DatetimeIndex

    Observations where wti_5d_lagged_return is unavailable (too early in
    the price series) are dropped silently.
    """
    feat_rows: list[list[float]] = []
    label_rows: list[int] = []
    ts_rows: list[pd.Timestamp] = []

    for obs in kept_obs:
        lagged = _compute_wti_5d_lagged_return(obs.decision_ts, prices)
        if lagged is None:
            continue
        fomc_indicator = 1.0 if obs.family == "fomc" else 0.0
        feat_rows.append([fomc_indicator, lagged])
        label_rows.append(1 if obs.return_path > 0 else 0)
        ts_rows.append(obs.decision_ts)

    if not feat_rows:
        feat_mat = np.empty((0, 2), dtype=float)
        label_arr = np.empty(0, dtype=int)
        ts_index = pd.DatetimeIndex([], tz="UTC")
        return feat_mat, label_arr, ts_index

    feat_mat = np.array(feat_rows, dtype=float)
    label_arr = np.array(label_rows, dtype=int)
    ts_index = pd.DatetimeIndex(ts_rows, tz="UTC")
    return feat_mat, label_arr, ts_index


def walk_forward_residuals(
    feat_mat: np.ndarray,
    label_arr: np.ndarray,
    decision_ts: pd.DatetimeIndex,
    *,
    warmup_weeks: int,
    refit_months: int,
) -> pd.Series:
    """Rolling-origin walk-forward fit; returns residuals indexed by decision_ts.

    Protocol (per prereg outer_protocol):
      - Skip the first warmup_weeks × 7 calendar days of the observation window
        (no predictions are made for those events; they contribute only to training).
      - For each calendar month after the warmup, fit a fresh
        LogisticRegressionFeasibilityModel on ALL events whose decision_ts is
        strictly before the month start, then predict every event whose
        decision_ts falls within that month.

    Residuals are computed as:
        residual = y_true_sign - y_pred_sign
    where y_true_sign ∈ {-1, +1} (converted from 0/1 labels) and
    y_pred_sign ∈ {-1, +1}, so residuals ∈ {-2, 0, +2}.

    Events with no training data available (fewer than 2 distinct classes seen
    in the training window) are skipped — the model cannot be fitted.
    """
    if len(feat_mat) == 0:
        return pd.Series(dtype=float, name="residual")

    # Warmup cutoff: decision_ts[0] + warmup_weeks * 7 days
    warmup_delta = pd.Timedelta(days=warmup_weeks * 7)
    warmup_end = decision_ts[0] + warmup_delta

    # Collect all months that contain at least one post-warmup event
    post_warmup_mask = decision_ts >= warmup_end
    if not post_warmup_mask.any():
        return pd.Series(dtype=float, name="residual")

    post_warmup_ts = decision_ts[post_warmup_mask]
    # Build sorted list of unique (year, month) pairs to iterate
    months = sorted(
        {(ts.year, ts.month) for ts in post_warmup_ts},
        key=lambda ym: ym,
    )

    residual_values: list[float] = []
    residual_ts: list[pd.Timestamp] = []

    for year, month in months:
        month_start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
        # End of month (exclusive): first day of next month
        if month == 12:
            month_end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
        else:
            month_end = pd.Timestamp(year=year, month=month + 1, day=1, tz="UTC")

        # Training set: all events with decision_ts strictly before month_start
        train_mask = decision_ts < month_start
        feats_train = feat_mat[train_mask]
        labels_train = label_arr[train_mask]

        if len(feats_train) < 2:
            # Not enough data to fit
            continue
        # Need both classes present
        if len(np.unique(labels_train)) < 2:
            continue

        model = LogisticRegressionFeasibilityModel()
        model.fit(feats_train, labels_train)

        # Test set: events in [month_start, month_end)
        test_mask = (decision_ts >= month_start) & (decision_ts < month_end)
        feats_test = feat_mat[test_mask]
        labels_test = label_arr[test_mask]
        ts_test = decision_ts[test_mask]

        if len(feats_test) == 0:
            continue

        # predict_sign returns {-1, +1}
        y_pred_sign = model.predict_sign(feats_test)
        # Convert 0/1 labels to ±1 signs
        y_true_sign = np.where(labels_test == 1, 1, -1).astype(int)
        # residual = y_true_sign - y_pred_sign  ∈ {-2, 0, +2}
        residuals_batch = (y_true_sign - y_pred_sign).astype(float)

        residual_values.extend(residuals_batch.tolist())
        residual_ts.extend(ts_test.tolist())

    if not residual_values:
        return pd.Series(dtype=float, name="residual")

    idx = pd.DatetimeIndex(residual_ts, tz="UTC")
    return pd.Series(residual_values, index=idx, name="residual").sort_index()


def write_residuals_csv(residuals: pd.Series, path: Path) -> None:
    """Write residuals to CSV with columns decision_ts (ISO 8601 UTC), residual."""
    df = pd.DataFrame(
        {
            "decision_ts": residuals.index.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "residual": residuals.values,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def invoke_harness_residual_mode(residuals_csv: Path, manifest_out: Path) -> dict:
    """Invoke tractability_v1 in Phase 3 residual mode and return the manifest."""
    cmd = [
        sys.executable,
        "-m",
        "feasibility.tractability_v1",
        "--families",
        "wpsr,fomc,opec_ministerial",
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


def write_report(manifest: dict, report_path: Path) -> None:
    """Write the Phase 3 audit verdict report.

    Covers: Gate 1 outcome, residual-HAC effective N, and Phase 3
    verdict (admissible / non-admissible per spec v1 §13).
    """
    created_at = manifest.get("created_at_utc", "unknown")
    decision = manifest.get("decision", {})
    n_star = decision.get("min_effective_n", "N/A")

    # Pull per-target HAC from manifest if present
    targets_block = manifest.get("targets", {})
    target_info = targets_block.get("wti_3d_return_sign", {})
    hac_block = target_info.get("n_hac_or_block_adjusted", {})
    newey_west = hac_block.get("newey_west", {})
    block_bootstrap_info = hac_block.get("block_bootstrap", {})
    hac_n = newey_west.get("point_estimate", "N/A")
    boot_n = block_bootstrap_info.get("point_estimate", "N/A")
    n_after_purge = target_info.get("n_after_purge_embargo", "N/A")

    # Phase 3 admission criterion: spec v1 §13 requires HAC N >= 250 AND
    # block-bootstrap N >= 250 on the residual series.
    hac_floor = 250
    boot_floor = 250
    hac_pass = isinstance(hac_n, int) and hac_n >= hac_floor
    boot_pass = isinstance(boot_n, int) and boot_n >= boot_floor
    if hac_pass and boot_pass:
        verdict = "ADMISSIBLE"
        verdict_detail = (
            f"Both HAC N ({hac_n}) >= {hac_floor} and "
            f"bootstrap N ({boot_n}) >= {boot_floor}. "
            "Candidate clears Phase 3 gate."
        )
    else:
        verdict = "NON-ADMISSIBLE"
        reasons: list[str] = []
        if not hac_pass:
            reasons.append(f"HAC N = {hac_n} < {hac_floor}")
        if not boot_pass:
            reasons.append(f"bootstrap N = {boot_n} < {boot_floor}")
        verdict_detail = "; ".join(reasons) + ". Candidate does not clear Phase 3 gate."

    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "# Phase 3 Audit — FOMC → WTI 3d Return Sign",
        "",
        "**Pre-reg**: `feasibility/preregs/2026-04-29-fomc_wti_3d.yaml`  ",
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
        "| families | wpsr, fomc, opec_ministerial |",
        f"| horizon_days | {HORIZON_DAYS} |",
        f"| purge_days | {PURGE_DAYS} |",
        f"| embargo_days | {EMBARGO_DAYS} |",
        f"| warmup_weeks | {WARMUP_WEEKS} |",
        "| refit_cadence | monthly |",
        "",
        "---",
        "",
        "## Gate 1 — effective N waterfall",
        "",
        "| Stage | N |",
        "| --- | --- |",
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
        f"Spec v1 §13 admission thresholds: HAC N >= {hac_floor} and "
        f"bootstrap N >= {boot_floor} on the residual series (not the raw target). "
        f"Walk-forward residuals were computed with a {WARMUP_WEEKS}-week warmup "
        "and monthly refit per the pre-reg outer_protocol.",
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
    parser.add_argument(
        "--skip-harness",
        action="store_true",
        help=(
            "Stop after writing residuals CSV; useful when the harness flags "
            "are not yet landed (Wave 2 delivery)."
        ),
    )
    args = parser.parse_args(argv)

    # --- Step 1: Load event families from PIT ---
    families = _resolve_families(["wpsr", "fomc", "opec_ministerial"])
    family_events = [load_family_decision_events(args.pit_root, fam) for fam in families]

    # --- Step 2: Load WTI prices ---
    wti_path = next((p for p in DEFAULT_WTI_PATHS if p.exists()), DEFAULT_WTI_PATHS[0])
    target_def = TargetDef(
        name="wti_3d_return_sign",
        price_path=wti_path,
        horizon_days=HORIZON_DAYS,
        metric="return_sign",
        forbidden_uses=("executable_futures_replay",),
    )
    prices, _ = load_target_prices(target_def)

    # --- Step 3-4: Build observations, apply post-2020 filter + purge/embargo ---
    obs = build_target_observations(family_events, prices, horizon_days=HORIZON_DAYS)
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

    # --- Step 5: Build features and labels ---
    feat_mat, label_arr, decision_ts = build_event_features_and_labels(kept_obs, prices)
    n_dropped = len(kept_obs) - feat_mat.shape[0]
    print(
        f"Feature matrix: {feat_mat.shape[0]} rows "
        f"(dropped {n_dropped} for missing lagged return)"
    )

    # --- Step 6: Walk-forward residuals ---
    residuals = walk_forward_residuals(
        feat_mat,
        label_arr,
        decision_ts,
        warmup_weeks=WARMUP_WEEKS,
        refit_months=REFIT_MONTHS,
    )
    print(
        f"Walk-forward residuals: {len(residuals)} events "
        f"(warmup skips first {WARMUP_WEEKS} weeks)"
    )

    # --- Step 7: Write residuals CSV ---
    write_residuals_csv(residuals, RESIDUALS_CSV)
    print(f"Wrote {len(residuals)} residuals to {RESIDUALS_CSV}")

    if args.skip_harness:
        print("Skipping harness invocation per --skip-harness")
        return 0

    # --- Step 8-9: Invoke harness in Phase 3 residual mode ---
    manifest = invoke_harness_residual_mode(RESIDUALS_CSV, PHASE3_MANIFEST)
    print(f"Phase 3 manifest: {PHASE3_MANIFEST}")
    print(json.dumps(manifest["decision"], indent=2))

    # --- Step 10: Write report ---
    write_report(manifest, PHASE3_REPORT)
    print(f"Phase 3 report: {PHASE3_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
