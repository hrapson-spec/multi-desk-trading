"""Audit-only OPEC ministerial model for WTI 3-day return sign.

Audit-only feasibility candidate; NOT a production desk.
Does not implement desks.base.DeskProtocol and is not importable as a desk.

Pre-reg: feasibility/preregs/2026-04-29-opec_ministerial_wti_3d.yaml
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

OPEC_FEATURE_COLUMNS: tuple[str, ...] = (
    "tightening_indicator",
    "easing_indicator",
    "deadlock_indicator",
    "jmmc_indicator",
)

TIGHTENING_TOKENS = frozenset(("cut", "extension", "delay"))
EASING_TOKENS = frozenset(("hike", "phase_out", "taper"))
DEADLOCK_TOKENS = frozenset(("deadlock", "failed"))


def classify_opec_event(event_label: str, event_type: str) -> dict[str, float]:
    """Map a release-time OPEC label/type to preregistered binary features."""
    lower_label = event_label.lower()
    return {
        "tightening_indicator": float(any(tok in lower_label for tok in TIGHTENING_TOKENS)),
        "easing_indicator": float(any(tok in lower_label for tok in EASING_TOKENS)),
        "deadlock_indicator": float(any(tok in lower_label for tok in DEADLOCK_TOKENS)),
        "jmmc_indicator": float(event_type == "jmmc_with_announcement"),
    }


def build_opec_event_features(events: pd.DataFrame) -> pd.DataFrame:
    """Build OPEC event-content features from event_label and event_type columns."""
    required = {"event_label", "event_type"}
    missing = sorted(required - set(events.columns))
    if missing:
        raise ValueError(f"OPEC events missing required columns: {missing}")

    rows = [
        classify_opec_event(str(row.event_label), str(row.event_type))
        for row in events.itertuples(index=False)
    ]
    return pd.DataFrame(rows, index=events.index, columns=OPEC_FEATURE_COLUMNS)


class OPECMinisterialLogisticModel:
    """Logistic regression model: OPEC event features -> WTI 3d sign."""

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
