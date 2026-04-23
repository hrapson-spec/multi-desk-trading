"""Rolling-origin walk-forward driver (ROWF, Regime A frozen).

Canonical Layer-3 outer protocol:
    - expanding window starting at a warm-up boundary
    - monthly refit cadence (forecaster fits on every available
      decision-eligible row strictly before the month's first
      decision_ts; frozen within the month)
    - daily forecast cadence
    - horizon_days = 5

The driver is shape-agnostic: it operates on a supplied returns series
and a supplied realised-outcome series (with decision_ts → realised
5-day Y mapping). The PITReader / desk wiring for real data is
handled by the paper-live loop (B6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pandas as pd


class DailyForecaster(Protocol):
    """Any object with a `fit_predict(history) -> quantile_vector` API.

    B0EWMAGaussian and B1Empirical satisfy this directly. A monthly-refit
    forecaster wraps its frozen-for-the-month parameters behind this
    interface, refitting internally only at month boundaries.
    """

    def fit_predict(self, returns_history: np.ndarray) -> tuple[float, ...]: ...


@dataclass(frozen=True)
class WalkForwardParams:
    warmup_weeks: int = 156
    refit_cadence: str = "monthly"  # "monthly" | "weekly" | "never"
    horizon_days: int = 5
    regime: str = "A"  # A = fully frozen hyperparameters


@dataclass(frozen=True)
class WalkForwardResult:
    decision_timestamps: pd.DatetimeIndex
    quantile_vectors: np.ndarray  # (N, K)
    realised_y: np.ndarray  # (N,)
    refit_month_ids: np.ndarray  # (N,) month-key for each row


def run_walk_forward(
    *,
    returns_series: pd.Series,
    realised_y_series: pd.Series,
    forecaster_factory,  # Callable[[], DailyForecaster]
    params: WalkForwardParams,
) -> WalkForwardResult:
    """Run the ROWF driver.

    Args:
        returns_series: pandas Series of one-period returns, indexed by
            the per-bar timestamp (UTC). Used to grow the training
            history and (for baselines) refit at each forecast tick.
        realised_y_series: the realised 5-day log return observable at
            decision_ts + horizon_days, aligned to the SAME index as
            `returns_series`. Rows where the horizon cannot be realised
            (last H-1 bars) must be NaN; the driver drops them.
        forecaster_factory: zero-arg factory returning a fresh
            DailyForecaster. Invoked once per refit boundary; the same
            instance is used for every daily forecast within the block.
        params: walk-forward hyperparameters.

    Returns:
        A WalkForwardResult with aligned decision_timestamps, quantile
        vectors, realised Y values, and refit_month_ids.

    Raises:
        ValueError on shape / alignment / warmup violations.
    """
    if not returns_series.index.equals(realised_y_series.index):
        raise ValueError("returns_series and realised_y_series must share an index")
    if returns_series.index.is_monotonic_increasing is False:
        raise ValueError("series index must be monotonically increasing")

    warmup_n = params.warmup_weeks * 5  # business days per week
    if returns_series.size < warmup_n + params.horizon_days:
        raise ValueError(
            f"series too short: need at least {warmup_n + params.horizon_days} rows, "
            f"got {returns_series.size}"
        )

    ts_index = returns_series.index
    returns = returns_series.to_numpy(dtype=float)
    realised_y = realised_y_series.to_numpy(dtype=float)

    out_ts: list[pd.Timestamp] = []
    out_qv: list[tuple[float, ...]] = []
    out_y: list[float] = []
    out_month: list[str] = []

    def _month_key(ts: pd.Timestamp) -> str:
        return f"{ts.year:04d}-{ts.month:02d}"

    # Refit cache: one forecaster per block (month or week).
    current_block_key: str | None = None
    current_forecaster: DailyForecaster | None = None

    for i in range(warmup_n, len(ts_index)):
        ts = pd.Timestamp(ts_index[i])
        if np.isnan(realised_y[i]):
            # Realisation not available for this decision timestamp.
            continue

        if params.refit_cadence == "monthly":
            block_key = _month_key(ts)
        elif params.refit_cadence == "weekly":
            block_key = f"{ts.isocalendar().year:04d}-W{ts.isocalendar().week:02d}"
        elif params.refit_cadence == "never":
            block_key = "all"
        else:
            raise ValueError(f"unknown refit_cadence: {params.refit_cadence!r}")

        if block_key != current_block_key:
            current_forecaster = forecaster_factory()
            current_block_key = block_key

        assert current_forecaster is not None
        # PIT-safe history: returns strictly before ts (exclusive).
        history = returns[:i]
        qv = current_forecaster.fit_predict(history)

        out_ts.append(ts)
        out_qv.append(tuple(qv))
        out_y.append(float(realised_y[i]))
        out_month.append(block_key)

    return WalkForwardResult(
        decision_timestamps=pd.DatetimeIndex(out_ts),
        quantile_vectors=np.asarray(out_qv, dtype=float),
        realised_y=np.asarray(out_y, dtype=float),
        refit_month_ids=np.asarray(out_month),
    )
