"""PIT-safe feature join over the public-data PIT store.

Public API: :func:`build_features`. For every (timestamp, source, series)
on the requested grid this module asks ``PITReader.as_of`` whether a row
is decision-eligible and forward-fills it. The eligibility comparator
inside ``as_of`` (``known_by_ts = COALESCE(revision_ts, release_ts)``,
v2/pit_store/reader.py:88) is the SOLE eligibility logic. This module
must never inspect ``observation_date`` or week-ending dates to decide
whether a row may be used — that's the leakage class the design
explicitly forbids and the leakage gate enforces.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import pandas as pd

from v2.ingest.event_calendar import build_event_calendar
from v2.ingest.public_data_registry import (
    eligible_for_model,
    load_registry,
)
from v2.pit_store.manifest import PITManifest
from v2.pit_store.reader import PITReader

Grid = Literal["daily", "weekly"]


def _grid_timestamps(start: datetime, end: datetime, grid: Grid) -> list[pd.Timestamp]:
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")
    if grid == "daily":
        freq = "D"
    elif grid == "weekly":
        freq = "W-WED"
    else:
        raise ValueError(f"unsupported grid: {grid!r}")
    idx = pd.date_range(pd.Timestamp(start), pd.Timestamp(end), freq=freq)
    return list(idx)


def _value_columns(df: pd.DataFrame) -> list[str]:
    """Pick the numeric data columns from a vintage frame.

    Heuristic: any non-key column with a numeric dtype. We exclude common
    metadata columns (``period``, ``observation_date``, ``release_date``,
    ``period_end``, ``date``, ``series``, ``source``).
    """
    skip = {
        "period",
        "period_end",
        "observation_date",
        "release_date",
        "date",
        "series",
        "source",
    }
    cols: list[str] = []
    for c in df.columns:
        if c in skip:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return cols


def _latest_value_for(
    reader: PITReader,
    source: str,
    dataset: str | None,
    series: str | None,
    ts: pd.Timestamp,
) -> dict[str, float]:
    """Return the latest value(s) for (source, series) decision-eligible at ``ts``.

    Returns an empty dict if no vintage is eligible. For multi-row
    vintages (e.g. a weekly history), the row with the largest available
    ``period`` (or last row) is taken — this is the contemporaneous read.
    """
    res = reader.as_of(
        source=source,
        dataset=dataset,
        series=series,
        as_of_ts=ts.to_pydatetime(),
    )
    if res is None:
        return {}
    df = res.data
    if df.empty:
        return {}
    # Pick the row with the latest "period" if such a column exists; else
    # the last row by position.
    period_col = None
    for candidate in ("period", "period_end", "observation_date", "date"):
        if candidate in df.columns:
            period_col = candidate
            break
    if period_col is not None:
        try:
            row = df.sort_values(period_col).iloc[-1]
        except TypeError:
            row = df.iloc[-1]
    else:
        row = df.iloc[-1]
    out: dict[str, float] = {}
    for col in _value_columns(df):
        val = row[col]
        if pd.isna(val):
            continue
        out[col] = float(val)
    return out


def _add_zscore_and_wow(
    df: pd.DataFrame, *, zscore_window: int, wow_lag: int
) -> pd.DataFrame:
    """Append rolling z-score and week-on-week delta columns to numeric features."""
    out = df.copy()
    for col in list(df.columns):
        if not col.endswith("__value"):
            continue
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        series = df[col].astype(float)
        rolling = series.rolling(window=zscore_window, min_periods=2)
        mean = rolling.mean()
        std = rolling.std()
        # Avoid divide-by-zero noise: where std is 0 or NaN, leave NaN.
        std_safe = std.where(std != 0.0)
        z = (series - mean) / std_safe
        out[f"{col}__zscore"] = z.astype(float)
        out[f"{col}__wow"] = series - series.shift(wow_lag)
    return out


def _add_cot_crowding(df: pd.DataFrame) -> pd.DataFrame:
    """If CFTC managed-money long/short and open interest columns exist,
    derive ``cot_crowding = (mm_long - mm_short) / open_interest``."""
    candidates = [
        (
            "cftc__067651__managed_money_long",
            "cftc__067651__managed_money_short",
            "cftc__067651__open_interest",
        ),
    ]
    out = df.copy()
    for long_col, short_col, oi_col in candidates:
        if long_col in out.columns and short_col in out.columns and oi_col in out.columns:
            oi_safe = out[oi_col].where(out[oi_col] != 0.0)
            out["cot_crowding"] = (out[long_col] - out[short_col]) / oi_safe
    return out


def build_features(
    *,
    manifest: PITManifest,
    reader: PITReader,
    grid: Grid,
    start: datetime,
    end: datetime,
    output_path: Path,
    zscore_window: int = 52 * 5,
) -> pd.DataFrame:
    """Build a PIT-safe feature DataFrame and write it to ``output_path``.

    For each timestamp ``t`` on the daily/weekly grid, every model-eligible
    registry entry is queried via ``reader.as_of(...)``. The returned
    rows form ``f"{source}__{series}__{field}"`` columns. Derived
    features (rolling z-score, week-on-week delta, COT crowding,
    event-calendar flags) are appended.

    Parameters
    ----------
    manifest : PITManifest
        Open manifest for the PIT store.
    reader : PITReader
        Canonical reader; its ``as_of`` is the SOLE eligibility check.
    grid : "daily" | "weekly"
        Grid frequency.
    start, end : datetime
        Bounds, inclusive. tz-aware preferred; tz-naive treated as UTC.
    output_path : Path
        Parquet output. Parents are created if missing.
    zscore_window : int
        Rolling window for z-score (default ``52 * 5`` = ~52 weeks of
        daily observations).

    Returns
    -------
    pd.DataFrame
        Indexed by ``DatetimeIndex`` named ``"timestamp"``.
    """
    del manifest  # reader holds the manifest; the parameter is part of the public API contract.
    timestamps = _grid_timestamps(start, end, grid)

    registry = load_registry()
    eligible = eligible_for_model(registry)

    # Per (source, series) column block. Pre-allocate the column set: we
    # advertise a stable schema regardless of which rows are eligible at
    # any particular `ts`. Default field is "value" — additional fields
    # surface dynamically when the reader returns them.
    col_blocks: dict[pd.Timestamp, dict[str, float]] = {ts: {} for ts in timestamps}
    seeded_columns: set[str] = set()
    for entry in eligible:
        source = entry.source
        dataset = entry.dataset
        series = entry.series_id
        prefix_parts = [source]
        if dataset is not None:
            prefix_parts.append(dataset)
        if series is not None:
            prefix_parts.append(series)
        prefix = "__".join(prefix_parts)
        seeded_columns.add(f"{prefix}__value")
        for ts in timestamps:
            vals = _latest_value_for(reader, source, dataset, series, ts)
            for field, v in vals.items():
                col_blocks[ts][f"{prefix}__{field}"] = v

    # Convert to a DataFrame, with the seeded schema acting as a floor.
    # Build index from timestamps directly so we don't lose rows when
    # nothing is eligible at a given ts.
    idx = pd.DatetimeIndex(timestamps, name="timestamp")
    discovered_columns = set()
    for ts_vals in col_blocks.values():
        discovered_columns.update(ts_vals.keys())
    all_columns = sorted(seeded_columns | discovered_columns)
    df = pd.DataFrame(index=idx, columns=all_columns, dtype=float)
    for ts, ts_vals in col_blocks.items():
        for col, v in ts_vals.items():
            df.at[ts, col] = v
    df = df.sort_index()

    # Derived features.
    if not df.empty:
        wow_lag = 7 if grid == "daily" else 1
        df = _add_zscore_and_wow(df, zscore_window=zscore_window, wow_lag=wow_lag)
        df = _add_cot_crowding(df)

        # Event-calendar columns (joined on date). Calendar is tz-naive
        # by date; convert each timestamp to its UTC calendar date.
        idx_utc = df.index.tz_convert("UTC") if df.index.tz is not None else df.index
        cal_start = (idx_utc.min() - pd.Timedelta(days=1)).date()
        cal_end = (idx_utc.max() + pd.Timedelta(days=1)).date()
        events = build_event_calendar(cal_start, cal_end)
        date_index = pd.DatetimeIndex(
            [pd.Timestamp(t.date()) for t in idx_utc], name="date"
        )
        events_aligned = events.reindex(date_index)
        events_aligned.index = df.index
        df = pd.concat([df, events_aligned], axis=1)

    # Persist.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Ensure boolean cols stay bool through parquet (pyarrow handles bool natively).
    df.to_parquet(output_path)
    return df


__all__ = ["build_features"]


# Re-export timedelta so callers that rely on `from .public_feature_join import *`
# do not lose access to it (used in test fixtures).
_ = timedelta
