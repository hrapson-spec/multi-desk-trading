"""Classical specialist for the Demand desk (plan §A, spec §5.3).

Structural mirror of `ClassicalSupplyModel`: consumes the demand
observation channel with the same [last, mean, std, trend] feature
vector over a 10-day lookback, fits ridge on the stationary log-return
target, and converts back to a price via the shared market_price.

Kept as a distinct class (vs a single shared generic) so per-desk
feature-engineering choices stay locally readable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 10
HORIZON_DEFAULT = 3
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalDemandModel:
    """Ridge(demand-channel features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(self, demand: np.ndarray, i: int) -> np.ndarray | None:
        if i < self.lookback + 1:
            return None
        window = demand[i - self.lookback : i]
        if np.any(~np.isfinite(window)):
            return None
        diffs = np.diff(window)
        if len(diffs) < 2:
            return None
        trend = float(np.polyfit(np.arange(len(window)), window, 1)[0])
        return np.array([float(window[-1]), float(window.mean()), float(window.std()), trend])

    def fit(self, demand: np.ndarray, market_price: np.ndarray) -> None:
        if len(demand) != len(market_price):
            raise ValueError(
                f"demand and market_price lengths differ: {len(demand)} vs {len(market_price)}"
            )
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(demand, i)
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
        self, demand: np.ndarray, market_price: np.ndarray, i: int
    ) -> tuple[float, float] | None:
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(demand, i)
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
