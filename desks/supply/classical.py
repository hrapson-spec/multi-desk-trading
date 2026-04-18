"""Classical specialist for the Supply desk (plan §A, spec §5.3).

Consumes the supply observation channel. Predicts a short-horizon log-
return on WTI front-month via ridge over a compact feature vector of
lagged supply statistics, then converts back to a price point-estimate
using the shared `market_price` reference.

Phase A synthetic regime: the supply channel is a direct observation of
the simulator's supply OU state with small Gaussian noise. In real
deployment this would be EIA WPSR + JODI + OPEC MOMR ingest — the Phase
1 asserted-capability test doesn't require the real feeds (plan §A).

Capability-claim debit: ridge-over-4-statistics is a deliberately modest
model — the architectural test is whether the desk emits a valid
Forecast that passes the three hard gates and contributes distinctly to
Shapley attribution, not whether this specific feature set is optimal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 10
HORIZON_DEFAULT = 3  # matches StorageCurveDesk's working classical horizon
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalSupplyModel:
    """Ridge(supply-channel features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(self, supply: np.ndarray, supply_level: np.ndarray, i: int) -> np.ndarray | None:
        """Compact per-timestep feature vector: [last, mean, std, trend]."""
        if i < self.lookback + 1:
            return None
        window = supply[i - self.lookback : i]
        if np.any(~np.isfinite(window)):
            return None
        if len(window) < 2:
            return None
        trend = float(np.polyfit(np.arange(len(window)), window, 1)[0])
        return np.array([float(window[-1]), float(window.mean()), float(window.std()), trend])

    def fit(
        self,
        supply: np.ndarray,
        supply_level_or_market_price: np.ndarray,
        market_price: np.ndarray | None = None,
    ) -> None:
        """Build (features at i, log-return over horizon) pairs and fit ridge.

        Uses the stationary log-return target (not the non-stationary price
        level) to avoid the cumulative-drift trap that afflicts raw-price
        targets — same design as ClassicalStorageCurveModel.
        """
        if market_price is None:
            supply_level = supply
            market_price = supply_level_or_market_price
        else:
            supply_level = supply_level_or_market_price

        if not (len(supply) == len(supply_level) == len(market_price)):
            raise ValueError(
                "supply, supply_level, and market_price lengths must match: "
                f"{len(supply)}, {len(supply_level)}, {len(market_price)}"
            )
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(supply, supply_level, i)
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
        supply: np.ndarray,
        supply_level_or_market_price: np.ndarray,
        market_price_or_i: np.ndarray | int,
        i: int | None = None,
    ) -> tuple[float, float] | None:
        """Returns (point_estimate_price, directional_score) or None."""
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        if i is None:
            supply_level = supply
            market_price = supply_level_or_market_price
            i = int(market_price_or_i)
        else:
            supply_level = supply_level_or_market_price
            market_price = market_price_or_i
        f = self._features(supply, supply_level, i)
        if f is None:
            return None
        log_ret_pred = float(f @ self.coef_ + self.intercept_)
        current_price = float(market_price[i - 1])
        point = current_price * float(np.exp(log_ret_pred))
        directional_score = log_ret_pred
        return point, directional_score

    def fingerprint(self) -> str:
        """Hashable summary of fitted parameters; embedded into provenance."""
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()
