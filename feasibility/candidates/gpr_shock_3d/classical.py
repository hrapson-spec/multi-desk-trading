"""Audit-only GPR shock-week model for WTI 3-day return sign.

Audit-only feasibility candidate; NOT a production desk.
Does not implement desks.base.DeskProtocol and is not importable as a desk.

Pre-reg: feasibility/preregs/2026-04-29-gpr_shock_wti_3d.yaml
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

GPR_VALUE_COLUMNS: tuple[str, ...] = (
    "GPRD_MA7",
    "GPRD_ACT",
    "GPRD_THREAT",
)

GPR_FEATURE_COLUMNS: tuple[str, ...] = (
    "gpr_shock_indicator",
    "gpr_ma7_level_z",
    "gpr_ma7_change_z",
    "gpr_act_z",
    "gpr_threat_z",
)


def _trailing_zscore(
    series: pd.Series,
    *,
    window: int,
    min_periods: int,
) -> pd.Series:
    trailing_mean = series.shift(1).rolling(window, min_periods=min_periods).mean()
    trailing_std = series.shift(1).rolling(window, min_periods=min_periods).std(ddof=0)
    trailing_std = trailing_std.replace(0.0, np.nan)
    return (series - trailing_mean) / trailing_std


def build_gpr_shock_features(
    event_values: pd.DataFrame,
    *,
    window: int = 52,
    min_periods: int = 26,
    shock_z: float = 1.5,
) -> pd.DataFrame:
    """Build release-time GPR shock features from weekly event-aligned values."""
    missing = sorted(set(GPR_VALUE_COLUMNS) - set(event_values.columns))
    if missing:
        raise ValueError(f"GPR values missing required columns: {missing}")

    features = pd.DataFrame(index=event_values.index)
    features["gpr_ma7_level_z"] = _trailing_zscore(
        event_values["GPRD_MA7"].astype(float),
        window=window,
        min_periods=min_periods,
    )

    ma7_change = event_values["GPRD_MA7"].astype(float).diff()
    features["gpr_ma7_change_z"] = _trailing_zscore(
        ma7_change,
        window=window,
        min_periods=min_periods,
    )
    features["gpr_act_z"] = _trailing_zscore(
        event_values["GPRD_ACT"].astype(float),
        window=window,
        min_periods=min_periods,
    )
    features["gpr_threat_z"] = _trailing_zscore(
        event_values["GPRD_THREAT"].astype(float),
        window=window,
        min_periods=min_periods,
    )
    features["gpr_shock_indicator"] = (features["gpr_ma7_level_z"] >= float(shock_z)).astype(float)
    return features.loc[:, GPR_FEATURE_COLUMNS].dropna(how="any")


class GPRShockLogisticModel:
    """Logistic regression model: GPR shock-week features -> WTI 3d sign."""

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
