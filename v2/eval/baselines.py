"""Layer-3 promotion baselines.

Both baselines produce quantile vectors on the v2 fixed grid for a 5-day
log-return target. A desk is promotable only if it beats BOTH baselines
on primary loss (pinball + approx-CRPS) in the outer walk-forward.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS


@dataclass(frozen=True)
class B0EWMAGaussian:
    """B0 — zero-mean Gaussian with EWMA volatility.

    Predictive distribution: N(0, σ̂_t²).
    σ̂_t is estimated from recent realised returns via EWMA with a
    declared half-life.

    Pre-registered hyperparameters (desk prereg):
        halflife_days: e.g. 60 for 5-day horizons.
    """

    halflife_days: float = 60.0

    def fit_predict(
        self,
        returns_history: np.ndarray,
    ) -> tuple[float, ...]:
        """Given a history of past one-period returns, return the quantile
        vector for the NEXT 5-day-log-return forecast.

        Caller is responsible for providing a PIT-safe returns series
        ending strictly before decision_ts.
        """
        r = np.asarray(returns_history, dtype=float).reshape(-1)
        if r.size == 0:
            raise ValueError("returns_history empty — cannot estimate sigma")
        # EWMA variance. Convert halflife to the EWMA decay factor.
        alpha = 1.0 - 2.0 ** (-1.0 / self.halflife_days)
        w = (1 - alpha) ** np.arange(r.size)[::-1]
        var = np.sum(w * r**2) / np.sum(w)
        sigma = float(np.sqrt(max(var, 1e-18)))
        return tuple(float(sigma * norm.ppf(q)) for q in FIXED_QUANTILE_LEVELS)


@dataclass(frozen=True)
class B1Empirical:
    """B1 — empirical 5-day return distribution, optionally time-decayed.

    Predictive distribution: empirical CDF of the training window, with
    exponential weighting if `time_decay_halflife_days` is set.

    Pre-registered hyperparameters:
        window_years: truncate history to the most recent N years.
        time_decay_halflife_days: None = uniform weighting.
    """

    window_years: float = 3.0
    time_decay_halflife_days: float | None = None

    def fit_predict(
        self,
        returns_history: np.ndarray,
    ) -> tuple[float, ...]:
        r = np.asarray(returns_history, dtype=float).reshape(-1)
        if r.size == 0:
            raise ValueError("returns_history empty")
        # Window truncation (assuming one observation per business day).
        max_n = int(self.window_years * 252)
        if r.size > max_n:
            r = r[-max_n:]
        if self.time_decay_halflife_days is None:
            return tuple(float(v) for v in np.quantile(r, FIXED_QUANTILE_LEVELS))
        # Exponentially time-weighted empirical quantile: weight older
        # observations less. Implemented via weighted quantile.
        decay = 0.5 ** (1.0 / self.time_decay_halflife_days)
        ages = np.arange(r.size)[::-1]
        weights = decay**ages
        weights /= weights.sum()
        # Weighted quantile by sorting values and integrating weight.
        order = np.argsort(r)
        sorted_r = r[order]
        sorted_w = weights[order]
        cum_w = np.cumsum(sorted_w)
        return tuple(float(np.interp(q, cum_w, sorted_r)) for q in FIXED_QUANTILE_LEVELS)
