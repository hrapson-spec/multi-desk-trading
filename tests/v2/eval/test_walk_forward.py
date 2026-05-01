"""Walk-forward driver tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from v2.eval import B0EWMAGaussian, WalkForwardParams, run_walk_forward


def _synthetic_series(n: int = 1_500, seed: int = 0) -> tuple[pd.Series, pd.Series]:
    """Build a daily return series + aligned 5-day realised-Y series."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2018-01-01", periods=n, freq="B", tz="UTC")
    daily_r = pd.Series(rng.standard_normal(n) * 0.01, index=idx)
    # Aligned 5-day realised log return: sum of next 5 daily returns.
    realised = daily_r.rolling(window=5).sum().shift(-5)
    return daily_r, realised


def test_walk_forward_produces_aligned_output():
    r, y = _synthetic_series()
    params = WalkForwardParams(warmup_weeks=26, refit_cadence="monthly")
    result = run_walk_forward(
        returns_series=r,
        realised_y_series=y,
        forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
        params=params,
    )
    # Every decision_ts must be after warm-up boundary.
    assert result.decision_timestamps.size > 0
    assert result.quantile_vectors.shape[0] == result.decision_timestamps.size
    assert result.realised_y.shape[0] == result.decision_timestamps.size
    assert result.refit_month_ids.shape[0] == result.decision_timestamps.size


def test_walk_forward_drops_rows_without_realised_y():
    r, y = _synthetic_series()
    # Last 5 bars have NaN realised_y by construction (rolling+shift).
    params = WalkForwardParams(warmup_weeks=26, refit_cadence="monthly")
    result = run_walk_forward(
        returns_series=r,
        realised_y_series=y,
        forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
        params=params,
    )
    # The last entry's decision_ts must be <= index[-1-5].
    last = result.decision_timestamps[-1]
    cutoff = r.index[-6]
    assert last <= cutoff


def test_walk_forward_monthly_refit_produces_monthly_block_keys():
    r, y = _synthetic_series()
    params = WalkForwardParams(warmup_weeks=26, refit_cadence="monthly")
    result = run_walk_forward(
        returns_series=r,
        realised_y_series=y,
        forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
        params=params,
    )
    # refit_month_ids are "YYYY-MM" strings; there should be as many distinct
    # month keys as full months covered.
    unique = set(result.refit_month_ids.tolist())
    assert all("-" in k for k in unique)
    assert len(unique) > 1


def test_walk_forward_weekly_refit():
    r, y = _synthetic_series(n=500)
    params = WalkForwardParams(warmup_weeks=13, refit_cadence="weekly")
    result = run_walk_forward(
        returns_series=r,
        realised_y_series=y,
        forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
        params=params,
    )
    unique = set(result.refit_month_ids.tolist())
    assert all(k.startswith("20") and "-W" in k for k in unique)


def test_walk_forward_too_short_rejected():
    r, y = _synthetic_series(n=50)
    params = WalkForwardParams(warmup_weeks=156)
    with pytest.raises(ValueError, match="too short"):
        run_walk_forward(
            returns_series=r,
            realised_y_series=y,
            forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
            params=params,
        )


def test_walk_forward_misaligned_series_rejected():
    r, y = _synthetic_series(n=300)
    y_short = y.iloc[:-10]
    params = WalkForwardParams(warmup_weeks=26)
    with pytest.raises(ValueError, match="share an index"):
        run_walk_forward(
            returns_series=r,
            realised_y_series=y_short,
            forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
            params=params,
        )


def test_walk_forward_quantile_vectors_are_monotone():
    r, y = _synthetic_series()
    params = WalkForwardParams(warmup_weeks=26)
    result = run_walk_forward(
        returns_series=r,
        realised_y_series=y,
        forecaster_factory=lambda: B0EWMAGaussian(halflife_days=60),
        params=params,
    )
    # Every row's quantile vector should be non-decreasing.
    diffs = np.diff(result.quantile_vectors, axis=1)
    assert (diffs >= -1e-12).all()
