"""Classical specialist for the Macro desk (plan §A, spec §5.3).

Consumes the xi (long-run equilibrium) observation channel. The
dominant signal in this channel is slow drift — so the Macro desk's
feature vector emphasises medium-horizon deltas and current level over
short-term variance.

Features:
  - Current xi level
  - 20-day xi change (medium-horizon drift proxy)
  - 40-day xi change (long-horizon drift proxy)
  - Rolling mean over the full lookback

Phase A debit: real Macro deepen requires FRED macro ingest + BVAR /
hierarchical-Bayes modelling per spec §5.3. The synthetic xi channel
is a direct observation of the Schwartz-Smith long factor with small
Gaussian noise; the classical model here is the simplest non-stub that
demonstrates the desk's architectural slot works end-to-end.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 60  # longer window — xi moves slowly
HORIZON_DEFAULT = 3
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalMacroModel:
    """Ridge(xi-channel features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(self, xi: np.ndarray, i: int) -> np.ndarray | None:
        if i < self.lookback + 1:
            return None
        window = xi[i - self.lookback : i]
        if np.any(~np.isfinite(window)):
            return None
        # Require at least 40 points for the long-horizon delta feature
        current = float(window[-1])
        delta_20 = float(window[-1] - window[-21]) if len(window) >= 21 else 0.0
        delta_40 = float(window[-1] - window[-41]) if len(window) >= 41 else 0.0
        rolling_mean = float(window.mean())
        return np.array([current, delta_20, delta_40, rolling_mean])

    def fit(self, xi: np.ndarray, market_price: np.ndarray) -> None:
        if len(xi) != len(market_price):
            raise ValueError(
                f"xi and market_price lengths differ: {len(xi)} vs {len(market_price)}"
            )
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(xi, i)
            if f is None:
                continue
            log_ret = float(
                np.log(market_price[i + self.horizon_days]) - np.log(market_price[i - 1])
            )
            X_list.append(f)
            y_list.append(log_ret)
        if len(X_list) < 5:
            raise ValueError(f"insufficient training rows: got {len(X_list)}; need ≥5")
        X = np.asarray(X_list, dtype=float)
        y = np.asarray(y_list, dtype=float)
        coef, intercept = fit_ridge(X, y, alpha=self.alpha)
        self.coef_ = coef
        self.intercept_ = intercept
        self.n_train_ = len(X_list)

    def predict(
        self, xi: np.ndarray, market_price: np.ndarray, i: int
    ) -> tuple[float, float] | None:
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(xi, i)
        if f is None:
            return None
        log_ret_pred = float(f @ self.coef_ + self.intercept_)
        current_price = float(market_price[i - 1])
        point = current_price * float(np.exp(log_ret_pred))
        directional_score = log_ret_pred
        return point, directional_score

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()
