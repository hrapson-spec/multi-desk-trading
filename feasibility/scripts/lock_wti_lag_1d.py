"""Lock the provisional WTI lag 1d audit candidate for forward holdout.

This script creates an immutable local lock artifact for the audit-only
candidate discovered after the 3d horizon pivot. It does not promote the
candidate to a desk; it freezes the files and metrics that the forward
holdout must not tune against.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from feasibility.scripts.audit_wti_lag_1d_phase3 import (
    EMBARGO_DAYS,
    FAMILY_NAMES,
    HORIZON_DAYS,
    MIN_TRAIN_EVENTS,
    PHASE3_MANIFEST,
    PURGE_DAYS,
    REFIT_MONTHS,
    RESIDUALS_CSV,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FORWARD_ROOT = REPO_ROOT / "feasibility" / "forward" / "wti_lag_1d"
LOCK_JSON = FORWARD_ROOT / "lock.json"
LOCK_REPORT = FORWARD_ROOT / "lock_report.md"

LOCKED_FILES: tuple[Path, ...] = (
    REPO_ROOT / "feasibility" / "preregs" / "2026-04-29-wti_lag_all_calendar_1d.yaml",
    REPO_ROOT / "feasibility" / "candidates" / "wti_lag_1d" / "classical.py",
    REPO_ROOT / "feasibility" / "scripts" / "audit_wti_lag_1d_phase3.py",
    REPO_ROOT / "feasibility" / "tractability_v1.py",
    REPO_ROOT / "contracts" / "target_variables.py",
    PHASE3_MANIFEST,
    RESIDUALS_CSV,
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rel(path: Path) -> str:
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def _load_phase3_metrics() -> dict[str, Any]:
    manifest = json.loads(PHASE3_MANIFEST.read_text())
    target = manifest["targets"]["wti_1d_return_sign"]
    n_block = target["n_hac_or_block_adjusted"]
    residual_rows = sum(1 for _ in RESIDUALS_CSV.open()) - 1
    return {
        "manifest_created_at_utc": manifest.get("created_at_utc"),
        "harness_action": manifest.get("decision", {}).get("action"),
        "n_after_purge_embargo": target.get("n_after_purge_embargo"),
        "n_star": target.get("n_star"),
        "hac_effective_n": n_block.get("newey_west", {}).get("point_estimate"),
        "block_bootstrap_effective_n": n_block.get("block_bootstrap", {}).get("point_estimate"),
        "scored_residuals": residual_rows,
        "model_accuracy": 0.5212,
        "zero_return_baseline_accuracy": 0.4703,
        "majority_baseline_accuracy": 0.5297,
        "gain_vs_zero_return_baseline_pp": 5.09,
        "gain_vs_majority_baseline_pp": -0.85,
        "verdict": "ADMISSIBLE_PROVISIONAL_FORWARD_LOCK_REQUIRED",
    }


def build_lock(locked_at_utc: datetime | None = None) -> dict[str, Any]:
    locked_at = locked_at_utc or datetime.now(UTC)
    missing = [path for path in LOCKED_FILES if not path.exists()]
    if missing:
        missing_rel = ", ".join(_rel(path) for path in missing)
        raise FileNotFoundError(f"cannot lock missing files: {missing_rel}")

    file_hashes = {
        _rel(path): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in LOCKED_FILES
    }
    lock_payload = {
        "lock_version": "wti_lag_1d.forward_lock.v1",
        "locked_at_utc": locked_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidate": {
            "id": "wti_lag_all_calendar_1d_audit_candidate",
            "status": "audit_only_provisional",
            "target_variable": "wti_front_1d_return_sign",
            "families": list(FAMILY_NAMES),
            "horizon_days": HORIZON_DAYS,
            "purge_days": PURGE_DAYS,
            "embargo_days": EMBARGO_DAYS,
            "feature_set": ["wti_prev_trading_day_1d_log_return"],
            "feature_leakage_guard": "strict_previous_trading_day_excludes_event_day",
            "model_class": ("feasibility.candidates.wti_lag_1d.classical.WTILag1DLogisticModel"),
            "model_hyperparameters": {
                "penalty": "l2",
                "C": 0.25,
                "fit_intercept": True,
                "solver": "lbfgs",
                "max_iter": 200,
                "random_state": 42,
            },
            "min_train_events": MIN_TRAIN_EVENTS,
            "refit_months": REFIT_MONTHS,
            "decision_threshold_probability_positive": 0.5,
        },
        "phase3_historical_metrics": _load_phase3_metrics(),
        "forward_holdout_rules": {
            "forbidden": [
                "change_features",
                "change_model_class",
                "change_hyperparameters",
                "change_thresholds",
                "peek_and_tune_on_forward_outcomes",
                "promote_without_forward_memo",
            ],
            "minimum_forward_scored_events_before_promotion_review": 60,
            "preferred_forward_scored_events_before_promotion_review": 100,
            "must_retest_zero_return_baseline": True,
            "must_retest_majority_baseline": True,
        },
        "locked_files": file_hashes,
        "capability_debits": [
            {
                "id": "D-WTI-LAG-1D-001",
                "severity": "blocking_for_promotion",
                "description": (
                    "Candidate was discovered after exploratory 3d failures; "
                    "historical pass is not promotion-grade."
                ),
            },
            {
                "id": "D-WTI-LAG-1D-002",
                "severity": "major",
                "description": (
                    "Historical model beats the registered zero-return baseline "
                    "but trails the realized majority-sign baseline."
                ),
            },
            {
                "id": "D-WTI-LAG-1D-003",
                "severity": "major",
                "description": (
                    "WTI target uses free FRED spot proxy and is forbidden for "
                    "executable CL/MCL replay."
                ),
            },
        ],
    }
    lock_id_source = json.dumps(lock_payload, sort_keys=True).encode()
    lock_payload["lock_id"] = hashlib.sha256(lock_id_source).hexdigest()[:16]
    return lock_payload


def write_lock(lock_payload: dict[str, Any]) -> None:
    FORWARD_ROOT.mkdir(parents=True, exist_ok=True)
    LOCK_JSON.write_text(json.dumps(lock_payload, indent=2, sort_keys=True) + "\n")

    metrics = lock_payload["phase3_historical_metrics"]
    report = [
        "# WTI Lag 1d Forward Lock",
        "",
        f"**Lock id**: `{lock_payload['lock_id']}`  ",
        f"**Locked at**: {lock_payload['locked_at_utc']}  ",
        "**Status**: audit-only provisional; forward holdout required.",
        "",
        "## Frozen Candidate",
        "",
        "| Field | Value |",
        "| --- | --- |",
        "| target | wti_front_1d_return_sign |",
        f"| families | {','.join(FAMILY_NAMES)} |",
        f"| horizon/purge/embargo | {HORIZON_DAYS}/{PURGE_DAYS}/{EMBARGO_DAYS} days |",
        "| feature | strict previous-trading-day WTI 1d log return |",
        "| model | fixed-hyperparameter logistic regression |",
        "",
        "## Historical Gate Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| n_after_purge_embargo | {metrics['n_after_purge_embargo']} |",
        f"| scored_residuals | {metrics['scored_residuals']} |",
        f"| HAC effective N | {metrics['hac_effective_n']} |",
        f"| block-bootstrap effective N | {metrics['block_bootstrap_effective_n']} |",
        f"| model_accuracy | {100.0 * metrics['model_accuracy']:.2f}% |",
        f"| gain_vs_zero_return_baseline | {metrics['gain_vs_zero_return_baseline_pp']:.2f} pp |",
        f"| gain_vs_majority_baseline | {metrics['gain_vs_majority_baseline_pp']:.2f} pp |",
        "",
        "## Promotion State",
        "",
        (
            "Not promoted. This lock starts a forward holdout because the "
            "candidate was found after exploratory screening and because the "
            "majority baseline remains a material debit."
        ),
        "",
    ]
    LOCK_REPORT.write_text("\n".join(report))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=LOCK_JSON)
    args = parser.parse_args(argv)
    if args.output != LOCK_JSON:
        raise ValueError("custom output is intentionally disabled for the forward lock")
    lock_payload = build_lock()
    write_lock(lock_payload)
    print(f"lock_id={lock_payload['lock_id']}")
    print(f"lock_json={LOCK_JSON}")
    print(f"lock_report={LOCK_REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
