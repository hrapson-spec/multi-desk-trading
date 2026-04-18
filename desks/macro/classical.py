"""Classical specialist for the Macro desk (plan §A, spec §5.3).

Consumes the xi observation channel plus a companion xi-level state. The
dominant signal in this channel is slow drift, so the Macro desk's
feature vector emphasises medium-horizon deltas, current level, and
level-gap context over short-term variance.

Features:
  - Current xi signal / previous xi signal / signal mean / signal trend
  - Current xi level
  - 10-day and 20-day xi-level changes
  - xi level gap vs rolling mean

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

LOOKBACK_DEFAULT = 30
HORIZON_DEFAULT = 3
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalMacroModel:
    """Ridge(xi-signal + xi-level features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(self, xi_signal: np.ndarray, xi_level: np.ndarray, i: int) -> np.ndarray | None:
        if i < self.lookback + 2:
            return None
        signal_window = xi_signal[i - self.lookback : i]
        level_window = xi_level[i - self.lookback : i]
        if np.any(~np.isfinite(signal_window)) or np.any(~np.isfinite(level_window)):
            return None
        signal_last = float(signal_window[-1])
        signal_prev = float(signal_window[-2])
        signal_mean = float(signal_window.mean())
        signal_trend = float(np.polyfit(np.arange(len(signal_window)), signal_window, 1)[0])
        level_last = float(level_window[-1])
        delta_10 = float(level_window[-1] - level_window[-11]) if len(level_window) >= 11 else 0.0
        delta_20 = float(level_window[-1] - level_window[-21]) if len(level_window) >= 21 else 0.0
        level_gap = float(level_last - level_window.mean())
        return np.array(
            [
                signal_last,
                signal_prev,
                signal_mean,
                signal_trend,
                signal_last - signal_prev,
                level_last,
                delta_10,
                delta_20,
                level_gap,
            ]
        )

    def fit(
        self,
        xi_signal: np.ndarray,
        xi_level_or_market_price: np.ndarray,
        market_price: np.ndarray | None = None,
    ) -> None:
        if market_price is None:
            xi_level = xi_signal
            market_price = xi_level_or_market_price
        else:
            xi_level = xi_level_or_market_price
        if not (len(xi_signal) == len(xi_level) == len(market_price)):
            raise ValueError(
                "xi_signal, xi_level, and market_price lengths differ: "
                f"{len(xi_signal)}, {len(xi_level)}, {len(market_price)}"
            )
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(xi_signal, xi_level, i)
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
        self,
        xi_signal: np.ndarray,
        xi_level_or_market_price: np.ndarray,
        market_price_or_i: np.ndarray | int,
        i: int | None = None,
    ) -> tuple[float, float] | None:
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        if i is None:
            xi_level = xi_signal
            market_price = xi_level_or_market_price
            i = int(market_price_or_i)
        else:
            xi_level = xi_level_or_market_price
            market_price = market_price_or_i
        f = self._features(xi_signal, xi_level, i)
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
