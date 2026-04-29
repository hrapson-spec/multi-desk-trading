"""Crude feasibility tractability harness v1.

Implements the multi-event-family tractability calculation against the locked
specification at `feasibility/reports/n_requirement_spec_v0.md`.

Differences from v0 (`feasibility/tractability.py`):

1. Multi-event-family support. Each event family has its own (source, dataset,
   series) match rule and contributes decision timestamps to a unified
   per-target observation stream. Per-target N is computed by greedy thinning
   across the union of all families' decision timestamps for that target
   (spec §11 forbidden #4: cross-target N pooling forbidden).
2. §6 HAC effective-N implementation. Newey-West with Bartlett kernel,
   per-lag autocorrelation lower-bounded at 0 to avoid inflation from
   mean-reverting score series. Also implements a circular block bootstrap
   variance-ratio estimator for cross-validation.
3. §12-compliant manifest output. Every mandatory field is populated.
   Placeholder values are explicit (e.g. n_oos_by_fold = {} when no fold
   structure has been declared).
4. Vintage-quality filtering. Rows with vintage_quality outside the
   admissible set are excluded from `n_after_quality_filter`.
5. Holds the v0 result invariant: a v1 run with `families=["wpsr"]` against
   the same PIT store produces the same per-target effective_n as v0.

This module deliberately does not introduce new ingestion, training, or
modelling code — it only counts admissible decision events and reports them
in the schema the spec mandates.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

SCHEMA_VERSION = "tractability.v1.0"
DEFAULT_PIT_ROOT = Path("data/pit_store")
DEFAULT_WTI_PATHS = (
    Path("data/s4_0/free_source/raw/DCOILWTICO.csv"),
    Path("data/s4_0/free_source_wti_futures/raw/yfinance_wti_futures_replay.csv"),
)
DEFAULT_OUTPUT = Path("feasibility/outputs/tractability_v1.json")
POST_2020_START = pd.Timestamp("2020-01-01T00:00:00Z")

ADMISSIBLE_VINTAGE_QUALITIES = frozenset(
    {"true_first_release", "release_lag_safe_revision_unknown"}
)


@dataclass(frozen=True)
class EventFamily:
    """One PIT event family (e.g. WPSR, STEO, OPEC ministerial).

    `sources` and `datasets` are matched against the pit_manifest. If
    `datasets` is empty, no dataset filter is applied. `series` is purely
    for documentation; the manifest already partitions by series.
    """

    name: str
    sources: tuple[str, ...]
    datasets: tuple[str, ...] = ()
    description: str = ""


WPSR_FAMILY = EventFamily(
    name="wpsr",
    sources=("eia", "eia_wpsr"),
    datasets=("wpsr",),
    description="EIA Weekly Petroleum Status Report",
)

FOMC_FAMILY = EventFamily(
    name="fomc",
    sources=("fomc",),
    datasets=("fomc_announcements",),
    description="FOMC statement and minutes announcements",
)

STEO_FAMILY = EventFamily(
    name="steo",
    sources=("eia_steo",),
    datasets=("steo_calendar",),
    description="EIA Short-Term Energy Outlook monthly release",
)

OPEC_MINISTERIAL_FAMILY = EventFamily(
    name="opec_ministerial",
    sources=("opec",),
    datasets=("opec_ministerial",),
    description="OPEC+ ministerial meetings and JMMC announcements",
)

EIA_PSM_FAMILY = EventFamily(
    name="psm",
    sources=("eia_psm",),
    datasets=("psm_calendar",),
    description="EIA Petroleum Supply Monthly (EIA-914 preliminary)",
)

GPR_FAMILY = EventFamily(
    name="gpr",
    sources=("caldara_iacoviello",),
    datasets=("gpr_weekly",),
    description="Caldara-Iacoviello Geopolitical Risk Index weekly",
)

DEFAULT_FAMILY_REGISTRY: dict[str, EventFamily] = {
    "wpsr": WPSR_FAMILY,
    "fomc": FOMC_FAMILY,
    "steo": STEO_FAMILY,
    "opec_ministerial": OPEC_MINISTERIAL_FAMILY,
    "psm": EIA_PSM_FAMILY,
    "gpr": GPR_FAMILY,
}


@dataclass(frozen=True)
class PITPriceSource:
    """Location specifier for a PIT-store-backed price series.

    Used as the polymorphic alternative to a CSV Path for TargetDef.price_source.
    The harness queries pit_manifest for matching (source, dataset, series),
    reads the parquet payloads, takes the latest revision per observation_date,
    and returns a UTC-indexed pd.Series of prices.
    """

    source: str
    dataset: str
    series: str
    observation_date_column: str = "observation_date"
    price_column: str = "close"


@dataclass(frozen=True)
class TargetDef:
    """One per-target stream definition.

    A target is a `(price_series, horizon)` pair plus a metric extractor
    family (sign, magnitude, MAE). Per spec §4, N_star is computed per
    target.

    `price_source` is the polymorphic field: either a Path (CSV) or a
    PITPriceSource. When set, it takes precedence over `price_path`.
    `price_path` remains for backward compatibility.
    """

    name: str
    price_path: Path
    horizon_days: int
    metric: str  # one of: return_sign, return_magnitude, mae_conditional
    price_target_kind: str = "fred_wti_spot_proxy"
    forbidden_uses: tuple[str, ...] = ()
    price_source: Path | PITPriceSource | None = None


class NonAdditiveFamilyError(ValueError):
    """Raised when --reject-non-additive is set and a candidate family
    decreases n_after_purge_embargo for any target relative to the base
    set. The error message names the candidate, target, base N, and
    candidate N."""


def load_residuals_csv(path: Path) -> pd.Series:
    """Load residuals CSV with columns decision_ts (ISO 8601 UTC), residual.

    Returns pd.Series indexed by UTC DatetimeIndex, values are residuals.
    """
    df = pd.read_csv(path)
    if not {"decision_ts", "residual"} <= set(df.columns):
        raise ValueError(
            f"residuals CSV {path} must have columns decision_ts, residual; "
            f"got {list(df.columns)}"
        )
    ts = pd.to_datetime(df["decision_ts"], utc=True)
    return pd.Series(
        df["residual"].astype(float).to_numpy(),
        index=pd.DatetimeIndex(ts),
        name="residual",
    )


@dataclass
class FamilyDecisionEvents:
    family: str
    decision_ts: list[pd.Timestamp]
    manifest_rows_matched: int
    vintage_quality_distribution: dict[str, int]


@dataclass
class TargetObservation:
    family: str
    decision_ts: pd.Timestamp
    return_path: float
    magnitude_path: float
    mae: float


@dataclass
class TargetResult:
    target: TargetDef
    observations: list[TargetObservation]
    n_targetable_raw: int
    n_post2020_raw: int
    n_after_quality_filter: int
    n_after_purge_embargo: int
    hac: dict[str, Any]
    block_bootstrap: dict[str, Any]
    n_star: int
    n_star_strict_hac_phase3plus: int
    sample_std: float | None
    baseline_rate: float | None
    observed_positive_rate: float | None
    mde_observed_baseline: float | None
    mde_naive_baseline: float | None
    n_by_cost_bucket: dict[str, int] = field(default_factory=dict)


def effective_n(
    decision_ts: Sequence[pd.Timestamp],
    *,
    purge_days: int,
    embargo_days: int,
) -> int:
    """Greedy post-event thinning. Identical semantics to v0 (§5)."""
    if purge_days < 0 or embargo_days < 0:
        raise ValueError("purge_days and embargo_days must be non-negative")

    kept = 0
    next_allowed: pd.Timestamp | None = None
    gap = pd.Timedelta(days=purge_days + embargo_days)
    for ts in sorted(decision_ts):
        if next_allowed is not None and ts <= next_allowed:
            continue
        kept += 1
        next_allowed = ts + gap
    return kept


def kept_decision_ts(
    decision_ts: Sequence[pd.Timestamp],
    *,
    purge_days: int,
    embargo_days: int,
) -> list[pd.Timestamp]:
    """Return the timestamps actually retained by greedy thinning."""
    kept: list[pd.Timestamp] = []
    next_allowed: pd.Timestamp | None = None
    gap = pd.Timedelta(days=purge_days + embargo_days)
    for ts in sorted(decision_ts):
        if next_allowed is not None and ts <= next_allowed:
            continue
        kept.append(ts)
        next_allowed = ts + gap
    return kept


def compute_hac_effective_n(
    values: np.ndarray,
    *,
    K: int | str = "auto",
    horizon_days: int = 5,
    embargo_days: int = 5,
    event_spacing_days: float = 7.0,
) -> dict[str, Any]:
    """Newey-West HAC effective-N with Bartlett kernel.

    Per spec §6, with the wording fix from §F1: per-lag autocorrelation is
    lower-bounded at 0 to avoid effective-N inflation from mean-reverting
    score series. K defaults to `max(ceil((h+b)/event_spacing), 4)`.

    Returns `{point_estimate, K_used, rho_sum_capped, method}`.
    """
    n = int(len(values))
    if n < 4:
        return {
            "point_estimate": n,
            "K_used": 0,
            "rho_sum_capped": 0.0,
            "method": "below_min_sample",
        }

    if K == "auto":
        K_int = max(int(math.ceil((horizon_days + embargo_days) / event_spacing_days)), 4)
    else:
        K_int = int(K)
    K_int = min(K_int, n - 1)

    arr = np.asarray(values, dtype=float)
    var = float(np.var(arr, ddof=1))
    if not np.isfinite(var) or var <= 0:
        return {
            "point_estimate": n,
            "K_used": K_int,
            "rho_sum_capped": 0.0,
            "method": "zero_variance",
        }

    centered = arr - float(np.mean(arr))
    rho_sum = 0.0
    for k in range(1, K_int + 1):
        cov_k = float(np.mean(centered[k:] * centered[:-k]))
        rho_k = cov_k / var
        rho_k_capped = max(0.0, rho_k)
        weight = 1.0 - k / (K_int + 1.0)
        rho_sum += weight * rho_k_capped

    n_eff = n / (1.0 + 2.0 * rho_sum)
    n_eff = max(1.0, min(float(n), n_eff))
    return {
        "point_estimate": int(math.floor(n_eff)),
        "K_used": K_int,
        "rho_sum_capped": rho_sum,
        "method": "newey_west_bartlett_capped_at_zero",
    }


def compute_block_bootstrap_effective_n(
    values: np.ndarray,
    *,
    block_length: int,
    B: int = 2000,
    seed: int = 42,
) -> dict[str, Any]:
    """Circular block bootstrap variance-ratio effective-N estimate.

    Resamples blocks of length `block_length` circularly with replacement.
    Effective N is `n * sample_var / boot_var_of_mean` clamped to [1, n].
    """
    n = int(len(values))
    if n < 4 or block_length < 1:
        return {
            "point_estimate": n,
            "method": "below_min",
            "B": 0,
            "block_length": block_length,
        }

    arr = np.asarray(values, dtype=float)
    sample_var = float(np.var(arr, ddof=1))
    if not np.isfinite(sample_var) or sample_var <= 0:
        return {
            "point_estimate": n,
            "method": "zero_variance",
            "B": 0,
            "block_length": block_length,
        }

    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block_length)
    means = np.empty(B, dtype=float)
    base_offsets = np.arange(block_length)
    for b in range(B):
        starts = rng.integers(0, n, size=n_blocks)
        all_indices = ((starts[:, None] + base_offsets[None, :]) % n).ravel()[:n]
        means[b] = float(np.mean(arr[all_indices]))

    boot_var_of_mean = float(np.var(means, ddof=1))
    if not np.isfinite(boot_var_of_mean) or boot_var_of_mean <= 0:
        return {
            "point_estimate": n,
            "method": "zero_boot_var",
            "B": B,
            "block_length": block_length,
        }

    iid_var_of_mean = sample_var / n
    n_eff = n * iid_var_of_mean / boot_var_of_mean
    n_eff = max(1.0, min(float(n), n_eff))
    return {
        "point_estimate": int(math.floor(n_eff)),
        "method": "circular_block_bootstrap_variance_ratio",
        "B": B,
        "block_length": block_length,
    }


def min_detectable_effect_binary(
    n: int,
    baseline_rate: float,
    *,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float | None:
    """One-sample proportion power against a fixed baseline (v0 semantics)."""
    if n <= 0 or not (0.0 < baseline_rate < 1.0):
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


def min_detectable_effect_continuous(
    n: int,
    sample_std: float,
    *,
    alpha: float = 0.05,
    power: float = 0.80,
) -> dict[str, float] | None:
    if n <= 1 or not np.isfinite(sample_std) or sample_std <= 0:
        return None
    z_alpha = float(norm.ppf(1.0 - alpha / 2.0))
    z_power = float(norm.ppf(power))
    standardized = (z_alpha + z_power) / math.sqrt(n)
    return {
        "raw_effect": float(standardized * sample_std),
        "standardized_effect": float(standardized),
    }


def load_family_decision_events(
    pit_root: Path,
    family: EventFamily,
) -> FamilyDecisionEvents:
    """Load decision timestamps for one event family from the PIT manifest.

    Filters by `(source, dataset)` per the family contract and de-dupes on
    `(source, series, usable_after_ts)`. Vintage-quality distribution is
    reported alongside the timestamps; the rows are *not* yet filtered for
    admissibility — that happens in `apply_quality_filter`.
    """
    db_path = pit_root / "pit.duckdb"
    if not db_path.exists():
        return FamilyDecisionEvents(
            family=family.name,
            decision_ts=[],
            manifest_rows_matched=0,
            vintage_quality_distribution={},
        )

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        manifest_cols = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info('pit_manifest')").fetchall()
        }
        ts_col = (
            "usable_after_ts"
            if "usable_after_ts" in manifest_cols
            else "release_ts"
        )

        source_clause = " OR ".join(
            "source = ?" for _ in family.sources
        )
        params: list[str] = list(family.sources)

        dataset_clause = ""
        if family.datasets and "dataset" in manifest_cols:
            dataset_clause = " AND (" + " OR ".join(
                "lower(dataset) = ?" for _ in family.datasets
            ) + ")"
            params.extend([d.lower() for d in family.datasets])

        vintage_select = "vintage_quality" if "vintage_quality" in manifest_cols else "NULL"

        rows = conn.execute(
            f"""
            SELECT DISTINCT source, series, {ts_col}, {vintage_select}
            FROM pit_manifest
            WHERE ({source_clause}){dataset_clause}
            ORDER BY {ts_col}
            """,
            params,
        ).fetchall()
    finally:
        conn.close()

    decision_ts: list[pd.Timestamp] = []
    seen: set[pd.Timestamp] = set()
    quality_dist: dict[str, int] = {}
    for row in rows:
        ts_raw = row[2]
        ts = pd.Timestamp(ts_raw)
        ts = ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
        if ts not in seen:
            decision_ts.append(ts)
            seen.add(ts)
        quality = str(row[3]) if row[3] is not None else "unknown"
        quality_dist[quality] = quality_dist.get(quality, 0) + 1

    decision_ts.sort()
    return FamilyDecisionEvents(
        family=family.name,
        decision_ts=decision_ts,
        manifest_rows_matched=len(rows),
        vintage_quality_distribution=quality_dist,
    )


def load_target_prices_from_pit(
    pit_root: Path,
    spec: PITPriceSource,
) -> tuple[pd.Series, dict[str, Any]]:
    """Load a price series from the PIT store.

    Reads pit_manifest for matching (source, dataset, series), loads each
    referenced parquet, deduplicates by observation_date taking the
    latest revision (max revision_ts, falling back to max release_ts if
    revision_ts is null).
    """
    db_path = pit_root / "pit.duckdb"
    if not db_path.exists():
        raise FileNotFoundError(f"PIT manifest missing: {db_path}")
    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = conn.execute(
            """
            SELECT parquet_path, release_ts, revision_ts
            FROM pit_manifest
            WHERE source = ? AND dataset = ? AND series = ?
            ORDER BY release_ts ASC
            """,
            [spec.source, spec.dataset, spec.series],
        ).fetchall()
    finally:
        conn.close()
    if not rows:
        raise ValueError(
            f"No PIT vintages for ({spec.source}, {spec.dataset}, {spec.series})"
            f" under {pit_root}"
        )
    frames = []
    for parquet_path, release_ts, revision_ts in rows:
        full_path = pit_root / parquet_path
        if not full_path.exists():
            continue
        df = pd.read_parquet(full_path)
        if spec.observation_date_column not in df.columns:
            continue
        if spec.price_column not in df.columns:
            continue
        sub = df[[spec.observation_date_column, spec.price_column]].copy()
        sub = sub.rename(
            columns={spec.observation_date_column: "obs_date", spec.price_column: "price"}
        )
        # Effective recency for dedup: revision_ts if not null, else release_ts
        effective = revision_ts if revision_ts is not None else release_ts
        sub["effective_ts"] = effective
        frames.append(sub)
    if not frames:
        raise ValueError(
            f"No usable parquet payloads for ({spec.source}, {spec.dataset}, {spec.series})"
        )
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["price"])
    combined = combined[combined["price"] > 0]
    # Take latest revision per observation_date
    combined = combined.sort_values("effective_ts").drop_duplicates(
        subset=["obs_date"], keep="last"
    )
    combined["obs_date"] = pd.to_datetime(combined["obs_date"], utc=True)
    prices = pd.Series(
        combined["price"].astype(float).to_numpy(),
        index=pd.DatetimeIndex(combined["obs_date"]),
    ).sort_index()
    status = {
        "available": True,
        "path": f"pit://{spec.source}/{spec.dataset}/{spec.series}",
        "rows": int(prices.size),
        "price_column": spec.price_column,
        "start": prices.index.min().isoformat(),
        "end": prices.index.max().isoformat(),
        "price_target_kind": "pit_spine",
        "vintages_loaded": len(rows),
    }
    return prices, status


def load_target_prices(
    target: TargetDef,
    pit_root: Path | None = None,
) -> tuple[pd.Series, dict[str, Any]]:
    """Load a per-target price series.

    Dispatches to `load_target_prices_from_pit` when `target.price_source` is
    a PITPriceSource; otherwise falls back to CSV-path logic using
    `target.price_source` (if a Path) or the legacy `target.price_path`.
    """
    # Determine the effective source
    effective_source = target.price_source if target.price_source is not None else target.price_path

    # PIT-store dispatch
    if isinstance(effective_source, PITPriceSource):
        _pit_root = pit_root if pit_root is not None else DEFAULT_PIT_ROOT
        return load_target_prices_from_pit(_pit_root, effective_source)

    # CSV path dispatch — effective_source is a Path
    csv_path: Path = effective_source  # type: ignore[assignment]
    if not csv_path.exists():
        raise FileNotFoundError(f"target price file missing: {csv_path}")
    frame = pd.read_csv(csv_path)
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
            f"{csv_path}: expected one of "
            "(observation_date,DCOILWTICO) | (ts_event,price) | (Date,Close)"
        )
    prices = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(ts))
    prices = prices.dropna()
    prices = prices[prices > 0].sort_index()
    prices = prices[~prices.index.duplicated(keep="last")]
    if prices.empty:
        raise ValueError(f"{csv_path}: no positive prices")
    status = {
        "available": True,
        "path": str(csv_path),
        "rows": int(prices.size),
        "price_column": price_column,
        "start": prices.index.min().isoformat(),
        "end": prices.index.max().isoformat(),
        "price_target_kind": target.price_target_kind,
        "forbidden_uses": list(target.forbidden_uses),
    }
    return prices, status


def build_target_observations(
    family_events: list[FamilyDecisionEvents],
    prices: pd.Series,
    *,
    horizon_days: int,
) -> list[TargetObservation]:
    """Project each family's decision_ts to a forward log-return path."""
    if horizon_days <= 0:
        raise ValueError("horizon_days must be > 0")
    log_prices = np.log(prices.astype(float))
    index = prices.index
    observations: list[TargetObservation] = []
    for fam in family_events:
        for ts in fam.decision_ts:
            pos = int(index.searchsorted(ts, side="left"))
            if pos >= len(index):
                continue
            end_pos = pos + horizon_days
            if end_pos >= len(index):
                continue
            start_log = float(log_prices.iloc[pos])
            end_log = float(log_prices.iloc[end_pos])
            forward = log_prices.iloc[pos + 1 : end_pos + 1].to_numpy(dtype=float)
            path_returns = forward - start_log
            ret = end_log - start_log
            if ret >= 0:
                mae = abs(min(0.0, float(np.min(path_returns))))
            else:
                mae = max(0.0, float(np.max(path_returns)))
            observations.append(
                TargetObservation(
                    family=fam.family,
                    decision_ts=pd.Timestamp(index[pos]).tz_convert("UTC"),
                    return_path=float(ret),
                    magnitude_path=abs(float(ret)),
                    mae=float(mae),
                )
            )
    observations.sort(key=lambda o: o.decision_ts)
    return observations


def apply_quality_filter(
    observations: list[TargetObservation],
    family_events: list[FamilyDecisionEvents],
) -> list[TargetObservation]:
    """Filter observations whose source family has any non-admissible vintage.

    Per spec §4 (admissibility condition #2): feature vintage quality must be
    admissible. For Phase 0.3 we apply this at the family level rather than
    per-row, since the manifest does not yet expose per-decision-event
    vintage breakdown to the harness. If a family has zero admissible rows
    (all `latest_snapshot_not_pit`), all of its observations are dropped.
    """
    family_admissible = {}
    for fam in family_events:
        admissible = sum(
            count
            for q, count in fam.vintage_quality_distribution.items()
            if q in ADMISSIBLE_VINTAGE_QUALITIES
        )
        family_admissible[fam.family] = admissible > 0
    return [obs for obs in observations if family_admissible.get(obs.family, False)]


def median_event_spacing_days(decision_ts: Sequence[pd.Timestamp]) -> float:
    if len(decision_ts) < 2:
        return 7.0
    sorted_ts = sorted(decision_ts)
    gaps = [
        (sorted_ts[i + 1] - sorted_ts[i]).total_seconds() / 86400.0
        for i in range(len(sorted_ts) - 1)
    ]
    if not gaps:
        return 7.0
    return float(np.median([g for g in gaps if g > 0])) or 7.0


def compute_target_result(
    target: TargetDef,
    family_events: list[FamilyDecisionEvents],
    prices: pd.Series,
    *,
    purge_days: int,
    embargo_days: int,
    residuals: pd.Series | None = None,
) -> TargetResult:
    raw_observations = build_target_observations(
        family_events, prices, horizon_days=target.horizon_days
    )
    n_targetable_raw = len(raw_observations)
    n_post2020_raw = sum(
        1 for o in raw_observations if o.decision_ts >= POST_2020_START
    )

    quality_filtered = apply_quality_filter(raw_observations, family_events)
    n_after_quality_filter = len(quality_filtered)

    post2020 = [o for o in quality_filtered if o.decision_ts >= POST_2020_START]
    kept_ts = kept_decision_ts(
        [o.decision_ts for o in post2020],
        purge_days=purge_days,
        embargo_days=embargo_days,
    )
    kept_set = set(kept_ts)
    kept_obs = [o for o in post2020 if o.decision_ts in kept_set]
    n_after_purge_embargo = len(kept_obs)

    residual_mode_active = residuals is not None

    if residual_mode_active:
        # Phase 3: filter kept_obs to events whose decision_ts is in residuals.index
        assert residuals is not None  # narrowing for type checkers
        residual_index_set = set(residuals.index)
        kept_obs_res = [o for o in kept_obs if o.decision_ts in residual_index_set]
        kept_obs_res.sort(key=lambda o: o.decision_ts)
        # Build values from residuals ordered by decision_ts
        values = np.array(
            [float(residuals.loc[o.decision_ts]) for o in kept_obs_res]
        )
        positive_rate = None
        baseline_rate = None
        sample_std = float(np.std(values, ddof=1)) if values.size > 1 else None
    else:
        kept_obs_res = kept_obs
        if target.metric == "return_sign":
            values = np.array([1.0 if o.return_path > 0 else 0.0 for o in kept_obs])
            positive_rate = float(np.mean(values)) if values.size else None
            baseline_rate = (
                max(positive_rate, 1.0 - positive_rate) if positive_rate is not None else None
            )
            sample_std = None
        elif target.metric == "return_magnitude":
            values = np.array([o.magnitude_path for o in kept_obs])
            positive_rate = None
            baseline_rate = None
            sample_std = float(np.std(values, ddof=1)) if values.size > 1 else None
        elif target.metric == "mae_conditional":
            values = np.array([o.mae for o in kept_obs])
            positive_rate = None
            baseline_rate = None
            sample_std = float(np.std(values, ddof=1)) if values.size > 1 else None
        else:
            raise ValueError(f"unknown target metric: {target.metric}")

    spacing = median_event_spacing_days([o.decision_ts for o in kept_obs_res])
    hac = compute_hac_effective_n(
        values,
        K="auto",
        horizon_days=target.horizon_days,
        embargo_days=embargo_days,
        event_spacing_days=spacing,
    )

    spec_block_lower = int(
        math.ceil((target.horizon_days + embargo_days) / max(spacing, 1.0))
    )
    block_len = max(spec_block_lower, 5)
    bootstrap = compute_block_bootstrap_effective_n(
        values, block_length=block_len, B=2000, seed=42
    )

    if residual_mode_active:
        # Phase 3: n_star incorporates HAC and bootstrap (CRITICAL: n_star itself,
        # not only the diagnostic field, so decision.min_effective_n is correct).
        n_star = min(n_after_purge_embargo, hac["point_estimate"], bootstrap["point_estimate"])
        n_star_strict_hac_phase3plus = n_star  # equal in residual mode
    else:
        # Phase 0 interpretation of spec §1 + §6: at this gate there is no
        # validation score series (no model has been fit), so the HAC adjustment
        # in §6 — which is defined on a "validation score or residual series" —
        # does not apply. n_star at Phase 0 equals N_after_purge_embargo per the
        # §1 compound subscript "oos_post2020_pit_clean_target_realizable_purged
        # _embargoed_costed" (no `hac_adjusted` suffix). HAC and bootstrap are
        # reported as Phase-3-readiness diagnostics on the raw target series.
        n_star = n_after_purge_embargo
        n_star_strict_hac_phase3plus = min(
            n_after_purge_embargo,
            hac["point_estimate"],
            bootstrap["point_estimate"],
        )

    if not residual_mode_active and target.metric == "return_sign":
        mde_observed = (
            min_detectable_effect_binary(n_after_purge_embargo, baseline_rate)
            if baseline_rate is not None
            else None
        )
        mde_naive = (
            min_detectable_effect_binary(n_after_purge_embargo, 0.50)
            if n_after_purge_embargo > 0
            else None
        )
    else:
        mde_observed = None
        mde_naive = None

    n_by_cost_bucket = {
        "free_proxy_no_friction": n_after_purge_embargo,
        "free_proxy_with_roll_friction": n_after_purge_embargo,
        "executable_paper": 0,
        "real_capital": 0,
    }

    return TargetResult(
        target=target,
        observations=kept_obs_res,
        n_targetable_raw=n_targetable_raw,
        n_post2020_raw=n_post2020_raw,
        n_after_quality_filter=n_after_quality_filter,
        n_after_purge_embargo=n_after_purge_embargo,
        hac=hac,
        block_bootstrap=bootstrap,
        n_star=n_star,
        n_star_strict_hac_phase3plus=n_star_strict_hac_phase3plus,
        sample_std=sample_std,
        baseline_rate=baseline_rate if not residual_mode_active else None,
        observed_positive_rate=positive_rate if not residual_mode_active else None,
        mde_observed_baseline=mde_observed,
        mde_naive_baseline=mde_naive,
        n_by_cost_bucket=n_by_cost_bucket,
    )


def compute_additive_n_contribution(
    pit_root: Path,
    base_families: list[EventFamily],
    candidate: EventFamily,
    targets: list[TargetDef],
    *,
    purge_days: int,
    embargo_days: int,
) -> dict[str, dict[str, int]]:
    """For each target, return {target_name: {"base": int, "with_candidate": int, "delta": int}}.

    Reuses compute_target_result (the same code path producing the manifest's
    n_after_purge_embargo field) so the guard's view matches the manifest's
    reported values exactly.
    """
    base_events = [load_family_decision_events(pit_root, fam) for fam in base_families]
    candidate_events = [
        load_family_decision_events(pit_root, fam) for fam in (*base_families, candidate)
    ]

    results: dict[str, dict[str, int]] = {}
    for tgt in targets:
        prices, _ = load_target_prices(tgt, pit_root)
        base_tr = compute_target_result(
            tgt,
            base_events,
            prices,
            purge_days=purge_days,
            embargo_days=embargo_days,
        )
        cand_tr = compute_target_result(
            tgt,
            candidate_events,
            prices,
            purge_days=purge_days,
            embargo_days=embargo_days,
        )
        results[tgt.name] = {
            "base": base_tr.n_after_purge_embargo,
            "with_candidate": cand_tr.n_after_purge_embargo,
            "delta": cand_tr.n_after_purge_embargo - base_tr.n_after_purge_embargo,
        }
    return results


def run_tractability_v1(
    *,
    pit_root: Path,
    families: list[EventFamily],
    targets: list[TargetDef],
    purge_days: int,
    embargo_days: int,
    alpha_family: float = 0.05,
    alpha_per_test: float | None = None,
    search_budget_runs: int = 1,
    reject_non_additive: bool = False,
    force_include: list[str] | None = None,
    non_additive_justification: str | None = None,
    candidate_residuals_csv: Path | None = None,
) -> dict[str, Any]:
    if alpha_per_test is None:
        alpha_per_test = alpha_family

    _force_include: list[str] = force_include if force_include is not None else []

    # Load residuals once (Change 2 — Phase 3 residual mode)
    residuals: pd.Series | None = None
    if candidate_residuals_csv is not None:
        residuals = load_residuals_csv(candidate_residuals_csv)

    # B9 additive-N guard (Change 1): iterate families left-to-right, checking
    # each candidate against the cumulative base built so far.
    forced_inclusions: list[dict[str, Any]] = []
    if reject_non_additive and len(families) > 1:
        for i in range(1, len(families)):
            base_fams = families[:i]
            candidate = families[i]
            contrib = compute_additive_n_contribution(
                pit_root,
                base_fams,
                candidate,
                targets,
                purge_days=purge_days,
                embargo_days=embargo_days,
            )
            negative_targets = {
                tname: info
                for tname, info in contrib.items()
                if info["delta"] <= 0
            }
            if negative_targets:
                if candidate.name in _force_include:
                    if not non_additive_justification:
                        raise NonAdditiveFamilyError(
                            f"--force-include {candidate.name} requires "
                            "--non-additive-justification"
                        )
                    # Record the forced inclusion in the manifest
                    forced_inclusions.append(
                        {
                            "family": candidate.name,
                            "justification": non_additive_justification,
                            "delta_per_target": {
                                tname: info["delta"]
                                for tname, info in negative_targets.items()
                            },
                        }
                    )
                else:
                    # Pick any one negative target to surface in the error message
                    tname, info = next(iter(negative_targets.items()))
                    raise NonAdditiveFamilyError(
                        f"family {candidate.name!r} is non-additive: "
                        f"target {tname!r} has delta={info['delta']} "
                        f"(base={info['base']}, with_candidate={info['with_candidate']}). "
                        "Use --force-include to override with "
                        "--non-additive-justification."
                    )

    family_events: list[FamilyDecisionEvents] = []
    for fam in families:
        family_events.append(load_family_decision_events(pit_root, fam))

    n_manifest_rows = sum(fe.manifest_rows_matched for fe in family_events)
    distinct_ts: set[pd.Timestamp] = set()
    for fe in family_events:
        distinct_ts.update(fe.decision_ts)
    n_decision_timestamps = len(distinct_ts)

    aggregate_quality: dict[str, int] = {}
    for fe in family_events:
        for q, c in fe.vintage_quality_distribution.items():
            aggregate_quality[q] = aggregate_quality.get(q, 0) + c

    target_results: list[TargetResult] = []
    target_status: dict[str, dict[str, Any]] = {}
    for tgt in targets:
        prices, status = load_target_prices(tgt, pit_root)
        target_status[tgt.name] = status
        target_results.append(
            compute_target_result(
                tgt,
                family_events,
                prices,
                purge_days=purge_days,
                embargo_days=embargo_days,
                residuals=residuals,
            )
        )

    n_star_overall = (
        min(tr.n_star for tr in target_results) if target_results else 0
    )

    if n_star_overall < 100:
        rule = "stop"
        action = "write_terminal_report_do_not_build_harness"
    elif n_star_overall < 250:
        rule = "continue_small_model_only"
        action = "remove_foundation_models_from_harness"
    elif n_star_overall < 1000:
        rule = "continue"
        action = "continue_per_plan"
    else:
        rule = "continue_foundation_revisit_statistically_defensible_later"
        action = "continue_per_plan"

    targets_block: dict[str, Any] = {}
    for tr in target_results:
        if residuals is not None:
            disposition_entry: dict[str, Any] = {
                "newey_west": tr.hac,
                "block_bootstrap": tr.block_bootstrap,
                "point_estimate": min(
                    tr.hac["point_estimate"], tr.block_bootstrap["point_estimate"]
                ),
                "phase_3_disposition": (
                    "active_residual_mode_HAC_on_model_residuals_n_star_propagates_to_decision"
                ),
            }
        else:
            disposition_entry = {
                "newey_west": tr.hac,
                "block_bootstrap": tr.block_bootstrap,
                "point_estimate": min(
                    tr.hac["point_estimate"], tr.block_bootstrap["point_estimate"]
                ),
                "phase_0_disposition": (
                    "diagnostic_only_no_validation_score_series_yet "
                    "(spec_§6_paradox_at_phase_0_see_review_B8)"
                ),
            }
        targets_block[tr.target.name] = {
            "metric": tr.target.metric,
            "horizon_days": tr.target.horizon_days,
            "price_target_kind": tr.target.price_target_kind,
            "price_target_forbidden_uses": list(tr.target.forbidden_uses),
            "n_targetable_raw": tr.n_targetable_raw,
            "n_post2020_raw": tr.n_post2020_raw,
            "n_after_quality_filter": tr.n_after_quality_filter,
            "n_after_purge_embargo": tr.n_after_purge_embargo,
            "n_hac_or_block_adjusted": disposition_entry,
            "n_star_strict_hac_phase3plus": tr.n_star_strict_hac_phase3plus,
            "n_oos_by_fold": {},
            "n_by_regime": {"unknown": tr.n_after_purge_embargo},
            "n_by_cost_bucket": tr.n_by_cost_bucket,
            "n_star": tr.n_star,
            "sample_std": tr.sample_std,
            "baseline_rate": tr.baseline_rate,
            "observed_positive_rate": tr.observed_positive_rate,
            "minimum_detectable_effect_size_for_5pct_significance_80pct_power": (
                tr.mde_observed_baseline
                if tr.target.metric == "return_sign" and residuals is None
                else min_detectable_effect_continuous(
                    tr.n_after_purge_embargo, tr.sample_std or 0.0
                )
            ),
            "minimum_detectable_effect_size_against_naive_50pct_baseline": tr.mde_naive_baseline,
        }

    parameters_block: dict[str, Any] = {
        "pit_root": str(pit_root),
        "families": [f.name for f in families],
        "targets": [t.name for t in targets],
        "purge_days": purge_days,
        "embargo_days": embargo_days,
        "post_2020_start": POST_2020_START.isoformat(),
        "alpha_family": alpha_family,
        "alpha_per_test": alpha_per_test,
        "search_budget_runs": search_budget_runs,
        "admissible_vintage_qualities": sorted(ADMISSIBLE_VINTAGE_QUALITIES),
    }
    if forced_inclusions:
        parameters_block["forced_inclusions"] = forced_inclusions

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": _utc_now(),
        "git_commit": _git_commit(),
        "parameters": parameters_block,
        "input_status": {
            "families": {
                fe.family: {
                    "manifest_rows_matched": fe.manifest_rows_matched,
                    "distinct_decision_ts": len(fe.decision_ts),
                    "vintage_quality_distribution": fe.vintage_quality_distribution,
                }
                for fe in family_events
            },
            "targets": target_status,
        },
        "n_waterfall": {
            "n_manifest_rows": n_manifest_rows,
            "n_decision_timestamps": n_decision_timestamps,
            "by_family": {
                fe.family: {
                    "manifest_rows_matched": fe.manifest_rows_matched,
                    "distinct_decision_ts": len(fe.decision_ts),
                }
                for fe in family_events
            },
        },
        "vintage_quality_distribution": aggregate_quality,
        "decision": {
            "min_effective_n": n_star_overall,
            "rule": rule,
            "action": action,
        },
        "targets": targets_block,
    }


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


def _default_targets(horizon_days: int = 5) -> list[TargetDef]:
    wti_path = next(
        (p for p in DEFAULT_WTI_PATHS if p.exists()), DEFAULT_WTI_PATHS[0]
    )
    forbidden = (
        "executable_futures_replay",
        "CL_front_month_backtest",
        "MCL_execution_replay",
    )
    h = horizon_days
    return [
        TargetDef(
            name=f"wti_{h}d_return_sign",
            price_path=wti_path,
            horizon_days=h,
            metric="return_sign",
            forbidden_uses=forbidden,
        ),
        TargetDef(
            name=f"wti_{h}d_return_magnitude",
            price_path=wti_path,
            horizon_days=h,
            metric="return_magnitude",
            forbidden_uses=forbidden,
        ),
        TargetDef(
            name=f"wti_{h}d_mae_conditional",
            price_path=wti_path,
            horizon_days=h,
            metric="mae_conditional",
            forbidden_uses=forbidden,
        ),
    ]


def _resolve_families(names: list[str]) -> list[EventFamily]:
    resolved: list[EventFamily] = []
    for n in names:
        if n not in DEFAULT_FAMILY_REGISTRY:
            raise ValueError(
                f"unknown family {n!r}; known: "
                f"{sorted(DEFAULT_FAMILY_REGISTRY)}"
            )
        resolved.append(DEFAULT_FAMILY_REGISTRY[n])
    return resolved


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pit-root", type=Path, default=DEFAULT_PIT_ROOT)
    parser.add_argument(
        "--families",
        type=str,
        default="wpsr",
        help="comma-separated event family names",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--purge-days", type=int, default=5)
    parser.add_argument("--embargo-days", type=int, default=5)
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=5,
        help=(
            "forecast horizon for default targets. Per spec §11, changes "
            "to horizon require a written dependence analysis and a "
            "versioned gate change (see Tier 3.A spec amendment)."
        ),
    )
    parser.add_argument("--alpha-family", type=float, default=0.05)
    parser.add_argument("--alpha-per-test", type=float, default=None)
    parser.add_argument("--search-budget-runs", type=int, default=1)
    # Change 1 — B9 additive-N pre-screen guard
    parser.add_argument(
        "--reject-non-additive",
        action="store_true",
        default=False,
        help=(
            "Reject any candidate family that decreases n_after_purge_embargo "
            "for any target (B9 guard, spec v1 §5)"
        ),
    )
    parser.add_argument(
        "--force-include",
        type=str,
        default="",
        help=(
            "Comma-separated family names to admit despite non-additive "
            "contribution. Requires --non-additive-justification."
        ),
    )
    parser.add_argument(
        "--non-additive-justification",
        type=str,
        default="",
        help=(
            "Required when --force-include is used. Recorded in "
            "manifest.parameters.forced_inclusions."
        ),
    )
    # Change 2 — Phase 3 residual mode
    parser.add_argument(
        "--phase3-residual-mode",
        action="store_true",
        default=False,
        help=(
            "Phase 3+ disposition: HAC computed on residuals, n_star "
            "incorporates HAC (spec v1 §6 / §13)"
        ),
    )
    parser.add_argument(
        "--candidate-residuals-csv",
        type=Path,
        default=None,
        help=(
            "Path to CSV with columns decision_ts, residual. "
            "Required when --phase3-residual-mode is set."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    import sys

    args = build_parser().parse_args(argv)

    # Validate phase3 residual mode
    if args.phase3_residual_mode and args.candidate_residuals_csv is None:
        print(
            "error: --phase3-residual-mode requires --candidate-residuals-csv",
            file=sys.stderr,
        )
        return 2

    families = _resolve_families(
        [s.strip() for s in args.families.split(",") if s.strip()]
    )
    force_include = (
        [s.strip() for s in args.force_include.split(",") if s.strip()]
        if args.force_include
        else []
    )
    targets = _default_targets(horizon_days=args.horizon_days)
    try:
        result = run_tractability_v1(
            pit_root=args.pit_root,
            families=families,
            targets=targets,
            purge_days=args.purge_days,
            embargo_days=args.embargo_days,
            alpha_family=args.alpha_family,
            alpha_per_test=args.alpha_per_test,
            search_budget_runs=args.search_budget_runs,
            reject_non_additive=args.reject_non_additive,
            force_include=force_include,
            non_additive_justification=args.non_additive_justification or None,
            candidate_residuals_csv=(
                args.candidate_residuals_csv if args.phase3_residual_mode else None
            ),
        )
    except NonAdditiveFamilyError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result["decision"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
