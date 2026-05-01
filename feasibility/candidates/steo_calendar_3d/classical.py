"""Audit-only STEO calendar-pulse model for WTI 3-day return sign.

Audit-only feasibility candidate; NOT a production desk.
Does not implement desks.base.DeskProtocol and is not importable as a desk.

Pre-reg: feasibility/preregs/2026-04-29-steo_calendar_wti_3d.yaml
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

STEO_FEATURE_COLUMNS: tuple[str, ...] = (
    "issue_month_sin",
    "issue_month_cos",
    "quarter_start_indicator",
    "release_gap_days_scaled",
    "release_date_override_indicator",
)


def _second_tuesday(year: int, month: int) -> date:
    first = date(year, month, 1)
    offset = (1 - first.weekday()) % 7
    first_tuesday = date(year, month, 1 + offset)
    return first_tuesday + timedelta(days=7)


def build_steo_calendar_features(events: pd.DataFrame) -> pd.DataFrame:
    """Build release-calendar features from STEO calendar PIT rows.

    The current STEO ingester emits calendar metadata only. These features are
    therefore a narrow calendar-pulse baseline, not an outlook-table surprise
    or forecast-revision model.
    """
    required = {"issue_label", "release_date"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"STEO events missing required columns: {missing}")

    if not isinstance(events.index, pd.DatetimeIndex):
        raise ValueError("STEO events must be indexed by release timestamp")

    release_dates = pd.to_datetime(events["release_date"])
    months = release_dates.dt.month.astype(float)
    month_angle = 2.0 * np.pi * months / 12.0

    release_gap_days = events.index.to_series().sort_index().diff().dt.total_seconds() / 86400.0
    release_gap_days = release_gap_days.reindex(events.index).fillna(30.0)
    override_indicator = [
        float(ts.date() != _second_tuesday(ts.year, ts.month)) for ts in release_dates
    ]

    features = pd.DataFrame(index=events.index)
    features["issue_month_sin"] = np.sin(month_angle).to_numpy(dtype=float)
    features["issue_month_cos"] = np.cos(month_angle).to_numpy(dtype=float)
    features["quarter_start_indicator"] = release_dates.dt.month.isin([1, 4, 7, 10]).astype(float)
    features["release_gap_days_scaled"] = (release_gap_days.astype(float) - 30.5) / 5.0
    features["release_date_override_indicator"] = override_indicator
    return features.loc[:, STEO_FEATURE_COLUMNS]


class STEOCalendarLogisticModel:
    """Logistic regression model: STEO calendar features -> WTI 3d sign."""

    def __init__(self) -> None:
        self._model: LogisticRegression | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Fit the fixed-hyperparameter preregistered logistic model."""
        model = LogisticRegression(
            penalty="l2",
            C=1.0,
            fit_intercept=True,
            solver="lbfgs",
            max_iter=100,
            random_state=42,
        )
        model.fit(X, y)
        self._model = model

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return P(y=1 | X), where y=1 means positive 3d WTI return."""
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
