"""Audit-only feasibility candidate for the FOMC → WTI 3-day return-sign hypothesis.

Audit-only feasibility candidate; NOT a production desk.
Does not implement desks.base.DeskProtocol and is not importable as a desk.

Pre-reg: feasibility/preregs/2026-04-29-fomc_wti_3d.yaml

This module provides a logistic regression model that predicts the sign of the
WTI front-month 3-day return around FOMC decision windows. It is evaluated
offline via feasibility/scripts/audit_fomc_3d_phase3.py in --phase3-residual-mode.

Decision-unit note: the controller at controller/decision.py:94 raw-sums
weight × point_estimate across desks. The oil family emits WTI_FRONT_1W_LOG_RETURN
(log-return units). This candidate emits wti_front_3d_return_sign (±1 sign units),
which cannot mix with log-return targets in the controller sum without corrupting
the combined signal. Hence this candidate stays audit-only under feasibility/candidates/.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression


class LogisticRegressionFeasibilityModel:
    """Logistic regression feasibility model: features → WTI 3d return sign (±1).

    Hyperparameters match the pre-reg at feasibility/preregs/2026-04-29-fomc_wti_3d.yaml:
      penalty='l2', C=1.0, fit_intercept=True, solver='lbfgs', max_iter=100,
      random_state=42.

    This class is NOT a DeskProtocol implementation. It has no on_schedule_fire,
    on_trigger, emit_target_variables, or emit_horizons. It is purely a statistical
    model for offline audit use.
    """

    def __init__(self) -> None:
        self._model: LogisticRegression | None = None

    # ------------------------------------------------------------------
    # Fit / predict
    # ------------------------------------------------------------------

    def fit(self, X: np.ndarray, y: np.ndarray) -> None:
        """Fit the logistic regression on design matrix X and binary labels y.

        Hyperparameters are fixed per the pre-reg:
          penalty='l2', C=1.0, fit_intercept=True, solver='lbfgs',
          max_iter=100, random_state=42.

        Args:
            X: Feature matrix, shape (n_samples, n_features).
            y: Binary labels {0, 1}, shape (n_samples,). Typically 1 where
               WTI 3d return > 0, 0 otherwise.
        """
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
        """Return predicted probabilities P(y=1 | X) in [0, 1].

        Args:
            X: Feature matrix, shape (n_samples, n_features).

        Returns:
            1-D array of probabilities, shape (n_samples,).

        Raises:
            RuntimeError: If the model has not been fitted yet.
        """
        if self._model is None:
            raise RuntimeError("model not fitted; call .fit() first")
        return self._model.predict_proba(X)[:, 1]

    def predict_sign(self, X: np.ndarray) -> np.ndarray:
        """Return predicted signs in {-1, +1}.

        Threshold: predict_proba > 0.5 → +1, else -1.

        Args:
            X: Feature matrix, shape (n_samples, n_features).

        Returns:
            1-D integer array of ±1, shape (n_samples,).

        Raises:
            RuntimeError: If the model has not been fitted yet.
        """
        proba = self.predict_proba(X)
        return np.where(proba > 0.5, 1, -1).astype(int)

    def residuals(
        self,
        X: np.ndarray,
        y: np.ndarray,
        decision_ts: pd.DatetimeIndex,
    ) -> pd.Series:
        """Compute per-decision residuals indexed by decision_ts (UTC).

        residual = y_true_sign - y_pred_sign

        y must encode ±1 signs directly (not 0/1 labels). The range of
        residual values is therefore {-2, 0, +2}.

        Args:
            X: Feature matrix, shape (n_samples, n_features).
            y: True sign labels in {-1, +1}, shape (n_samples,).
            decision_ts: UTC DatetimeIndex of length n_samples.

        Returns:
            pd.Series with name="residual", indexed by decision_ts (UTC).

        Raises:
            RuntimeError: If the model has not been fitted yet.
            ValueError: If lengths of X, y, decision_ts do not match.
        """
        if len(X) != len(y) or len(X) != len(decision_ts):
            raise ValueError(
                f"X, y, and decision_ts must have the same length; "
                f"got {len(X)}, {len(y)}, {len(decision_ts)}"
            )
        y_true_sign = np.asarray(y, dtype=int)
        y_pred_sign = self.predict_sign(X)
        residual_values = y_true_sign - y_pred_sign

        # Ensure the index is UTC-aware.
        if decision_ts.tzinfo is None:
            idx = decision_ts.tz_localize("UTC")
        else:
            idx = decision_ts.tz_convert("UTC")

        return pd.Series(residual_values, index=idx, name="residual")

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    def is_fit(self) -> bool:
        """Return True if the model has been fitted."""
        return self._model is not None
