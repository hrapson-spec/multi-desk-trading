"""Classical specialist for the Storage & Curve desk (spec §5.3 model-ladder step 2).

A small ridge-regression model over simple price features. Not the full
CatBoost-on-COT specialist envisioned in the desk spec: in this synthetic-only
regime (§1.2) there is no COT data, and CatBoost is not in the dependency set.
This class occupies the classical-specialist slot for **pipeline validation**
— that the fit/predict loop composes cleanly with the bus, grading harness,
and gate runner — not as an alpha claim.

Capability-claim debit: "classical specialist prototyped as ridge-over-price-
features because (a) CatBoost + COT ingestion not yet integrated, (b) synthetic
regime lacks real COT data. Alpha-grade build is a v1.x deepen item."
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class ClassicalStorageCurveModel:
    """Ridge regression: (recent returns, rolling vol, trend) → price at t+horizon.

    Fit-time contract: `.fit(prices)` uses only index i strictly before the
    prediction target; no cross-split leakage. Predict-time contract:
    `.predict(prices, i)` reads only prices[:i]; returns None if the lookback
    window doesn't fit.
    """

    lookback: int = 10
    horizon_days: int = 7
    alpha: float = 1.0  # ridge penalty

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    # ------------------------------------------------------------------
    # Features
    # ------------------------------------------------------------------

    def _features(self, prices: np.ndarray, i: int) -> np.ndarray | None:
        """Features from prices[:i] only. None if history too short."""
        if i < self.lookback + 1:
            return None
        window = prices[i - self.lookback : i]
        log_returns = np.diff(np.log(window))
        if len(log_returns) < 2:
            return None
        trend = float(np.polyfit(np.arange(len(log_returns)), log_returns, 1)[0])
        return np.array(
            [
                float(log_returns[-1]),
                float(np.mean(log_returns)),
                float(np.std(log_returns)),
                trend,
            ]
        )

    # ------------------------------------------------------------------
    # Fit / predict
    # ------------------------------------------------------------------

    def fit(self, prices: np.ndarray) -> None:
        """Fit on (features at i, log_return i→i+horizon_days) pairs.

        We model the stationary log-return target rather than the price level
        to avoid the non-stationarity trap (features are return-space but a
        raw-price target drifts with the cumulative path).
        """
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(prices) - self.horizon_days):
            f = self._features(prices, i)
            if f is None:
                continue
            log_ret = float(np.log(prices[i + self.horizon_days]) - np.log(prices[i - 1]))
            X_list.append(f)
            y_list.append(log_ret)

        if len(X_list) < 5:
            raise ValueError(
                f"insufficient training rows: got {len(X_list)}; "
                f"need ≥5 (lookback={self.lookback}, horizon={self.horizon_days})"
            )

        X = np.asarray(X_list, dtype=float)
        y = np.asarray(y_list, dtype=float)
        X_mean = X.mean(axis=0)
        y_mean = float(y.mean())
        Xc = X - X_mean
        yc = y - y_mean
        # Ridge closed-form: (XᵀX + αI)β = Xᵀy
        XtX = Xc.T @ Xc + self.alpha * np.eye(X.shape[1])
        Xty = Xc.T @ yc
        self.coef_ = np.linalg.solve(XtX, Xty)
        self.intercept_ = y_mean - float(X_mean @ self.coef_)
        self.n_train_ = len(X_list)

    def predict(self, prices: np.ndarray, i: int) -> tuple[float, float] | None:
        """Return (point_estimate_price, directional_score) or None.

        point_estimate is converted back to a price via the current price;
        directional_score is the signed predicted log-return (Gate 2 input).
        """
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(prices, i)
        if f is None:
            return None
        log_ret_pred = float(f @ self.coef_ + self.intercept_)
        current_price = float(prices[i - 1])
        point = current_price * float(np.exp(log_ret_pred))
        directional_score = log_ret_pred
        return point, directional_score

    # ------------------------------------------------------------------
    # Provenance helper — for Forecast.provenance.model_* fields
    # ------------------------------------------------------------------

    def fingerprint(self) -> str:
        """Hashable summary of fitted parameters; embedded into provenance."""
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + _hex_hash_of_array(params)


def _hex_hash_of_array(a: np.ndarray) -> str:
    import hashlib

    h = hashlib.sha256()
    h.update(a.tobytes())
    return h.hexdigest()
