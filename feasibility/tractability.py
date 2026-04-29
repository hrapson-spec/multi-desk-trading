"""Crude feasibility tractability calculation.

This module answers the first harness question: how many point-in-time
WPSR-conditioned observations are actually available after purge and embargo?

It intentionally refuses to manufacture EIA/WPSR rows from a release calendar.
If the PIT store has no WPSR vintages, the correct tractability result is
effective_n = 0 and the harness should stop before modelling work.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

DEFAULT_PIT_ROOT = Path("data/pit_store")
DEFAULT_WTI_PATHS = (
    Path("data/s4_0/free_source_wti_futures/raw/yfinance_wti_futures_replay.csv"),
    Path("data/s4_0/free_source/raw/DCOILWTICO.csv"),
)
DEFAULT_OUTPUT = Path("feasibility/outputs/tractability_v0.json")
DEFAULT_TERMINAL_REPORT = Path("feasibility/reports/terminal_tractability_v0.md")
POST_2020_START = pd.Timestamp("2020-01-01T00:00:00Z")


@dataclass(frozen=True)
class Observation:
    decision_ts: pd.Timestamp
    return_5d: float
    magnitude_5d: float
    mae_conditional_on_direction_5d: float


def effective_n(observations: list[Observation], purge_days: int, embargo_days: int) -> int:
    """Count non-overlapping observations after purge and walk-forward embargo.

    Observations are sorted by decision timestamp. A retained observation blocks
    the interval from its decision timestamp through `purge_days + embargo_days`.
    This is the conservative thinning needed before any downstream walk-forward
    validation: weekly WPSR rows with a 5-day horizon and 5-day embargo become
    approximately every-other-event observations.
    """
    if purge_days < 0 or embargo_days < 0:
        raise ValueError("purge_days and embargo_days must be non-negative")

    kept = 0
    next_allowed: pd.Timestamp | None = None
    gap = pd.Timedelta(days=purge_days + embargo_days)
    for obs in sorted(observations, key=lambda item: item.decision_ts):
        if next_allowed is not None and obs.decision_ts <= next_allowed:
            continue
        kept += 1
        next_allowed = obs.decision_ts + gap
    return kept


def min_detectable_effect(
    n: int,
    baseline_rate: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float | None:
    """Minimum detectable absolute lift for a binary target.

    Uses a normal-approximation one-sample proportion power equation against a
    fixed baseline rate. The return value is in proportion points, e.g. 0.08
    means an 8 percentage-point lift over the baseline rate.
    """
    if n <= 0:
        return None
    if not (0.0 < baseline_rate < 1.0):
        return None
    if not (0.0 < alpha < 1.0 and 0.0 < power < 1.0):
        raise ValueError("alpha and power must be in (0, 1)")

    z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
    z_power = float(norm.ppf(power))

    def required_gap(p1: float) -> float:
        se0 = math.sqrt(baseline_rate * (1.0 - baseline_rate) / n)
        se1 = math.sqrt(p1 * (1.0 - p1) / n)
        return (p1 - baseline_rate) - (z_alpha * se0 + z_power * se1)

    upper = 1.0 - 1e-12
    if required_gap(upper) < 0:
        return None
    p1 = brentq(required_gap, baseline_rate + 1e-12, upper)
    return float(p1 - baseline_rate)


def min_detectable_continuous_effect(
    n: int,
    sample_std: float,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict[str, float] | None:
    """Minimum detectable paired mean difference for a continuous target."""
    if n <= 1 or not np.isfinite(sample_std) or sample_std <= 0:
        return None
    z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
    z_power = float(norm.ppf(power))
    standardized = (z_alpha + z_power) / math.sqrt(n)
    raw = standardized * sample_std
    return {
        "raw_effect": float(raw),
        "standardized_effect": float(standardized),
    }


def run_tractability(
    *,
    pit_root: Path,
    wti_path: Path | None,
    purge_days: int,
    embargo_days: int,
    horizon_days: int,
) -> dict[str, Any]:
    chosen_wti = _choose_wti_path(wti_path)
    wpsr_dates, wpsr_status = load_wpsr_release_dates(pit_root)
    prices, price_status = load_wti_prices(chosen_wti)
    observations = build_observations(
        wpsr_dates,
        prices,
        horizon_days=horizon_days,
    )

    common = {
        "raw_n": len(observations),
        "effective_n_after_purge_embargo": effective_n(
            observations, purge_days, embargo_days
        ),
        "post_2020_effective_n": effective_n(
            [obs for obs in observations if obs.decision_ts >= POST_2020_START],
            purge_days,
            embargo_days,
        ),
    }

    targets = {
        "return_sign_5d": _binary_target_payload(observations, common),
        "return_magnitude_5d": _continuous_target_payload(
            observations,
            common,
            values=[obs.magnitude_5d for obs in observations],
            effect_unit="absolute_5d_log_return",
        ),
        "mae_conditional_on_direction_5d": _continuous_target_payload(
            observations,
            common,
            values=[obs.mae_conditional_on_direction_5d for obs in observations],
            effect_unit="absolute_adverse_5d_log_return",
        ),
    }

    min_effective_n = min(
        target["effective_n_after_purge_embargo"] for target in targets.values()
    )
    if min_effective_n < 100:
        decision = "stop"
        action = "write_terminal_report_do_not_build_harness"
    elif min_effective_n < 250:
        decision = "continue_small_model_only"
        action = "remove_foundation_models_from_harness"
    elif min_effective_n < 1000:
        decision = "continue"
        action = "continue_per_plan"
    else:
        decision = "continue_foundation_revisit_statistically_defensible_later"
        action = "continue_per_plan"

    return {
        "schema_version": "tractability.v0.1",
        "created_at_utc": _utc_now(),
        "git_commit": _git_commit(),
        "parameters": {
            "pit_root": str(pit_root),
            "wti_path": str(chosen_wti),
            "purge_days": purge_days,
            "embargo_days": embargo_days,
            "horizon_days": horizon_days,
            "post_2020_start": POST_2020_START.isoformat(),
        },
        "input_status": {
            "wpsr": wpsr_status,
            "wti": price_status,
        },
        "decision": {
            "min_effective_n": min_effective_n,
            "rule": decision,
            "action": action,
        },
        "targets": targets,
    }


def load_wpsr_release_dates(pit_root: Path) -> tuple[list[pd.Timestamp], dict[str, Any]]:
    """Load EIA/WPSR release timestamps from the existing PIT manifest."""
    pit_root = Path(pit_root)
    db_path = pit_root / "pit.duckdb"
    if not db_path.exists():
        return [], {
            "available": False,
            "reason": "missing_pit_manifest",
            "path": str(db_path),
            "rows": 0,
        }

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT source, series, release_ts
            FROM pit_manifest
            WHERE source IN ('eia', 'eia_wpsr')
               OR lower(source) LIKE '%wpsr%'
               OR lower(series) LIKE '%wpsr%'
            ORDER BY release_ts
            """
        ).fetchall()
    finally:
        conn.close()

    dates = sorted(
        {
            pd.Timestamp(row[2], tz="UTC") if pd.Timestamp(row[2]).tzinfo is None
            else pd.Timestamp(row[2]).tz_convert("UTC")
            for row in rows
        }
    )
    return dates, {
        "available": bool(dates),
        "reason": "ok" if dates else "no_wpsr_rows_in_manifest",
        "path": str(db_path),
        "manifest_rows_matched": len(rows),
        "distinct_release_ts": len(dates),
        "sources": sorted({str(row[0]) for row in rows}),
    }


def load_wti_prices(path: Path) -> tuple[pd.Series, dict[str, Any]]:
    """Load a local WTI price CSV into a UTC-indexed price series."""
    if not path.exists():
        raise FileNotFoundError(f"WTI price file missing: {path}")
    frame = pd.read_csv(path)
    if {"observation_date", "DCOILWTICO"} <= set(frame.columns):
        ts = pd.to_datetime(frame["observation_date"], utc=True)
        values = pd.to_numeric(frame["DCOILWTICO"], errors="coerce")
        price_column = "DCOILWTICO"
    elif {"ts_event", "price"} <= set(frame.columns):
        ts = pd.to_datetime(frame["ts_event"], utc=True)
        values = pd.to_numeric(frame["price"], errors="coerce")
        price_column = "price"
    elif {"Date", "Close"} <= set(frame.columns):
        ts = pd.to_datetime(frame["Date"], utc=True)
        values = pd.to_numeric(frame["Close"], errors="coerce")
        price_column = "Close"
    else:
        raise ValueError(
            f"{path} must contain either observation_date/DCOILWTICO, "
            "ts_event/price, or Date/Close columns"
        )

    prices = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(ts))
    prices = prices.dropna()
    prices = prices[prices > 0].sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    if prices.empty:
        raise ValueError(f"{path} produced no positive WTI prices")

    return prices, {
        "available": True,
        "path": str(path),
        "rows": int(prices.size),
        "price_column": price_column,
        "start": prices.index.min().isoformat(),
        "end": prices.index.max().isoformat(),
    }


def build_observations(
    wpsr_release_dates: list[pd.Timestamp],
    prices: pd.Series,
    *,
    horizon_days: int,
) -> list[Observation]:
    """Build WPSR-conditioned 5d return / magnitude / MAE observations."""
    if horizon_days <= 0:
        raise ValueError("horizon_days must be > 0")
    if not wpsr_release_dates:
        return []

    log_prices = np.log(prices.astype(float))
    observations: list[Observation] = []
    index = prices.index
    for release_ts in sorted(wpsr_release_dates):
        pos = int(index.searchsorted(release_ts, side="left"))
        if pos >= len(index):
            continue
        end_pos = pos + horizon_days
        if end_pos >= len(index):
            continue

        start_log = float(log_prices.iloc[pos])
        end_log = float(log_prices.iloc[end_pos])
        forward_path = log_prices.iloc[pos + 1 : end_pos + 1].to_numpy(dtype=float)
        path_returns = forward_path - start_log
        ret = end_log - start_log
        if ret >= 0:
            mae = abs(min(0.0, float(np.min(path_returns))))
        else:
            mae = max(0.0, float(np.max(path_returns)))
        observations.append(
            Observation(
                decision_ts=pd.Timestamp(index[pos]).tz_convert("UTC"),
                return_5d=float(ret),
                magnitude_5d=abs(float(ret)),
                mae_conditional_on_direction_5d=float(mae),
            )
        )
    return observations


def write_terminal_report(result: dict[str, Any], path: Path) -> None:
    """Write a stop report when the tractability gate fails."""
    path.parent.mkdir(parents=True, exist_ok=True)
    decision = result["decision"]
    wpsr = result["input_status"]["wpsr"]
    wti = result["input_status"]["wti"]
    lines = [
        "# Feasibility Harness v0 Terminal Report — Tractability Gate",
        "",
        f"Created: {result['created_at_utc']}",
        f"Git commit: `{result['git_commit']}`",
        "",
        "## Verdict",
        "",
        f"- Rule: `{decision['rule']}`",
        f"- Action: `{decision['action']}`",
        f"- Minimum effective N: `{decision['min_effective_n']}`",
        "",
        "The harness stops at Phase 0.3. No modelling code should be written "
        "for this track until the PIT WPSR data spine exists and the "
        "tractability calculation is re-run.",
        "",
        "## Blocking Finding",
        "",
        f"- WPSR input status: `{wpsr.get('reason')}`",
        f"- PIT manifest path: `{wpsr.get('path')}`",
        f"- Matched WPSR manifest rows: `{wpsr.get('manifest_rows_matched', 0)}`",
        (
            f"- WTI input status: local proxy present with `{wti.get('rows')}` rows "
            f"from `{wti.get('start')}` to `{wti.get('end')}`"
        ),
        "",
        "This is a data-spine failure, not a model failure. It is a successful "
        "feasibility outcome because it prevents spending weeks on an "
        "underpowered or non-existent sample.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _binary_target_payload(
    observations: list[Observation],
    common: dict[str, int],
) -> dict[str, Any]:
    if observations:
        positive_rate = float(np.mean([obs.return_5d > 0 for obs in observations]))
        baseline_rate = max(positive_rate, 1.0 - positive_rate)
    else:
        positive_rate = None
        baseline_rate = None
    mde = (
        min_detectable_effect(common["effective_n_after_purge_embargo"], baseline_rate)
        if baseline_rate is not None
        else None
    )
    return {
        **common,
        "baseline_rate": baseline_rate,
        "observed_positive_rate": positive_rate,
        "minimum_detectable_effect_size_for_5pct_significance_80pct_power": mde,
        "effect_unit": "absolute_proportion_point_lift",
    }


def _continuous_target_payload(
    observations: list[Observation],
    common: dict[str, int],
    *,
    values: list[float],
    effect_unit: str,
) -> dict[str, Any]:
    sample_std = float(np.std(values, ddof=1)) if len(values) > 1 else None
    mde = (
        min_detectable_continuous_effect(
            common["effective_n_after_purge_embargo"],
            sample_std,
        )
        if sample_std is not None
        else None
    )
    return {
        **common,
        "sample_std": sample_std,
        "minimum_detectable_effect_size_for_5pct_significance_80pct_power": mde,
        "effect_unit": effect_unit,
    }


def _choose_wti_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    for path in DEFAULT_WTI_PATHS:
        if path.exists():
            return path
    return DEFAULT_WTI_PATHS[0]


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-root", type=Path, default=DEFAULT_PIT_ROOT)
    parser.add_argument("--wti-path", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--terminal-report", type=Path, default=DEFAULT_TERMINAL_REPORT)
    parser.add_argument("--purge-days", type=int, default=5)
    parser.add_argument("--embargo-days", type=int, default=5)
    parser.add_argument("--horizon-days", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_tractability(
        pit_root=args.pit_root,
        wti_path=args.wti_path,
        purge_days=args.purge_days,
        embargo_days=args.embargo_days,
        horizon_days=args.horizon_days,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    if result["decision"]["min_effective_n"] < 100:
        write_terminal_report(result, args.terminal_report)
    print(json.dumps(result["decision"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
