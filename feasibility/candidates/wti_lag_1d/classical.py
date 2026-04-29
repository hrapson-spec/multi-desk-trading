"""Audit-only WTI previous-trading-day lag model for WTI 1-day return sign.

Audit-only feasibility candidate; NOT a production desk.
Does not implement desks.base.DeskProtocol and is not importable as a desk.

Pre-reg: feasibility/preregs/2026-04-29-wti_lag_all_calendar_1d.yaml
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

WTI_LAG_FEATURE_COLUMNS: tuple[str, ...] = ("wti_prev_trading_day_1d_log_return",)


def strict_previous_trading_day_log_return(
    decision_ts: pd.Timestamp,
    prices: pd.Series,
    *,
    lag_days: int = 1,
) -> float | None:
    """Return a lagged WTI log return known before the event's calendar day.

    Daily WTI proxy rows are date-stamped, not intraday-vintaged. To avoid
    using a same-day daily value before it could be known, this feature uses
    the last price observation strictly before the decision timestamp's UTC
    calendar date.
    """
    if lag_days <= 0:
        raise ValueError("lag_days must be positive")
    if prices.empty:
        return None

    idx = prices.index
    ts = (
        decision_ts.tz_convert("UTC")
        if decision_ts.tzinfo is not None
        else decision_ts.tz_localize("UTC")
    )
    day_start = pd.Timestamp(ts.date(), tz="UTC")
    pos = int(idx.searchsorted(day_start, side="left")) - 1
    prior_pos = pos - lag_days
    if pos < 0 or prior_pos < 0:
        return None

    p_t = float(prices.iloc[pos])
    p_lag = float(prices.iloc[prior_pos])
    if p_t <= 0 or p_lag <= 0:
        return None
    return float(np.log(p_t / p_lag))


class WTILag1DLogisticModel:
    """Logistic regression model: strict WTI lag -> WTI 1d sign."""

    def __init__(self) -> None:
        self._model: LogisticRegression | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Fit the fixed-hyperparameter audit model."""
        model = LogisticRegression(
            penalty="l2",
            C=0.25,
            fit_intercept=True,
            solver="lbfgs",
            max_iter=200,
            random_state=42,
        )
        model.fit(X, y)
        self._model = model

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return P(y=1 | X), where y=1 means positive 1d WTI return."""
        if self._model is None:
            raise RuntimeError("model not fitted; call .fit() first")
        return self._model.predict_proba(X)[:, 1]

    def predict_sign(self, X: np.ndarray) -> np.ndarray:
        """Return predicted signs in {-1, +1}; threshold is P(y=1) > 0.5."""
        proba = self.predict_proba(X)
        return np.where(proba > 0.5, 1, -1).astype(int)

    def residuals(
        self,
        X: np.ndarray,
        y: np.ndarray,
        decision_ts: pd.DatetimeIndex,
    ) -> pd.Series:
        """Compute y_true_sign - y_pred_sign residuals indexed by decision_ts."""
        if len(X) != len(y) or len(X) != len(decision_ts):
            raise ValueError(
                "X, y, and decision_ts must have the same length; "
                f"got {len(X)}, {len(y)}, {len(decision_ts)}"
            )
        y_true_sign = np.asarray(y, dtype=int)
        y_pred_sign = self.predict_sign(X)
        residual_values = y_true_sign - y_pred_sign

        idx = (
            decision_ts.tz_localize("UTC")
            if decision_ts.tzinfo is None
            else decision_ts.tz_convert("UTC")
        )
        return pd.Series(residual_values, index=idx, name="residual")

    def is_fit(self) -> bool:
        """Return True if the model has been fitted."""
        return self._model is not None
