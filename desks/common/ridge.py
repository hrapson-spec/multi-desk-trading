"""Closed-form ridge regression helpers shared across desk classicals.

fit_ridge(X, y, alpha) → (coef, intercept)
  Solves (XᵀX + αI)β = Xᵀy on centered data and reconstructs the
  intercept. Numpy-only, no sklearn dependency.

predict_ridge(coef, intercept, X) → ndarray

This is the same closed-form already inlined in
desks/storage_curve/classical.py; extracting it lets the 4 new
specialists share the solver without duplicating 15 lines each.
"""

from __future__ import annotations

import numpy as np


def fit_ridge(X: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> tuple[np.ndarray, float]:
    """Closed-form ridge on (X, y). Returns (coef, intercept)."""
    if X.ndim != 2:
        raise ValueError(f"X must be 2D; got shape {X.shape}")
    if y.ndim != 1:
        raise ValueError(f"y must be 1D; got shape {y.shape}")
    if X.shape[0] != y.shape[0]:
        raise ValueError(f"X and y row counts differ: {X.shape[0]} vs {y.shape[0]}")
    if X.shape[0] < 5:
        raise ValueError(f"need ≥5 training rows; got {X.shape[0]}")

    X_mean = X.mean(axis=0)
    y_mean = float(y.mean())
    Xc = X - X_mean
    yc = y - y_mean
    xtx = Xc.T @ Xc + alpha * np.eye(X.shape[1])
    xty = Xc.T @ yc
    coef = np.linalg.solve(xtx, xty)
    intercept = y_mean - float(X_mean @ coef)
    return coef, intercept


def predict_ridge(coef: np.ndarray, intercept: float, X: np.ndarray) -> np.ndarray:
    """Apply a fitted ridge to a (rows × features) matrix."""
    out: np.ndarray = X @ coef + intercept
    return out
