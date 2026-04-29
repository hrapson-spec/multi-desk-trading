"""Audit-only WPSR inventory-surprise model for WTI 3-day return sign.

Audit-only feasibility candidate; NOT a production desk.
Does not implement desks.base.DeskProtocol and is not importable as a desk.

Pre-reg: feasibility/preregs/2026-04-29-wpsr_inventory_wti_3d.yaml
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

REQUIRED_WPSR_SERIES: tuple[str, ...] = (
    "WCESTUS1",  # commercial crude inventories excluding SPR
    "WGTSTUS1",  # finished motor gasoline inventories
    "WDISTUS1",  # distillate fuel oil inventories
    "WPULEUS3",  # refinery utilization
    "WCRIMUS2",  # crude imports
    "WCREXUS2",  # crude exports
)

WPSR_FEATURE_COLUMNS: tuple[str, ...] = (
    "crude_stock_change_z",
    "product_stock_change_z",
    "refinery_utilization_change_z",
    "net_import_change_z",
)


def _trailing_change_zscore(
    series: pd.Series,
    *,
    window: int,
    min_periods: int,
) -> pd.Series:
    """Return current weekly change z-scored against prior changes only."""
    changes = series.astype(float).diff()
    trailing_mean = changes.shift(1).rolling(window, min_periods=min_periods).mean()
    trailing_std = changes.shift(1).rolling(window, min_periods=min_periods).std(ddof=0)
    trailing_std = trailing_std.replace(0.0, np.nan)
    return (changes - trailing_mean) / trailing_std


def build_wpsr_inventory_features(
    panel: pd.DataFrame,
    *,
    window: int = 52,
    min_periods: int = 26,
) -> pd.DataFrame:
    """Build release-time WPSR inventory features from a PIT-safe WPSR panel.

    The input panel must be indexed by WPSR release timestamp and include the
    raw WPSR series listed in REQUIRED_WPSR_SERIES. Every feature uses the
    current release's value/change and normalizes against prior releases only.
    """
    missing = sorted(set(REQUIRED_WPSR_SERIES) - set(panel.columns))
    if missing:
        raise ValueError(f"WPSR panel missing required series: {missing}")

    crude_stock = panel["WCESTUS1"]
    product_stock = panel["WGTSTUS1"] + panel["WDISTUS1"]
    refinery_utilization = panel["WPULEUS3"]
    net_imports = panel["WCRIMUS2"] - panel["WCREXUS2"]

    features = pd.DataFrame(index=panel.index)
    features["crude_stock_change_z"] = _trailing_change_zscore(
        crude_stock,
        window=window,
        min_periods=min_periods,
    )
    features["product_stock_change_z"] = _trailing_change_zscore(
        product_stock,
        window=window,
        min_periods=min_periods,
    )
    features["refinery_utilization_change_z"] = _trailing_change_zscore(
        refinery_utilization,
        window=window,
        min_periods=min_periods,
    )
    features["net_import_change_z"] = _trailing_change_zscore(
        net_imports,
        window=window,
        min_periods=min_periods,
    )
    return features.dropna(how="any")


class WPSRInventoryLogisticModel:
    """Logistic regression model: WPSR inventory features -> WTI 3d sign."""

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
