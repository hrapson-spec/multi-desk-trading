"""Classical model for the merged oil demand-nowcast desk (v1.16).

Ridge-level head on the demand observation channel + demand-level state.
Feature vector mixes short-horizon signal summaries (last, prev, mean,
std, trend, delta) with level context (level_last, level_gap). Ridge on
the stationary log-return target; the desk unpacks the return head as
its controller-facing point_estimate. Horizon pinned at 7 days to match
`WTI_FRONT_1W_LOG_RETURN`.

Inlined from the legacy `ClassicalDemandModel` at the post-C12 cleanup
wave (was previously inherited; legacy `desks/demand/` dir is deleted
alongside this inline). Full mixed-frequency state-space / dynamic-factor
nowcast is a §7.3 escalation under debit D1 per the commission at
`docs/pm/oil_demand_nowcast_engineering_commission.md`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 10
HORIZON_DEFAULT = 7  # v1.16: 1-week emission horizon (was 3 in pre-v1.16)
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalOilDemandNowcastModel:
    """Ridge(demand-signal + demand-level features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(
        self, demand: np.ndarray, demand_level: np.ndarray, i: int
    ) -> np.ndarray | None:
        if i < self.lookback + 2:
            return None
        window = demand[i - self.lookback : i]
        level_window = demand_level[i - self.lookback : i]
        if np.any(~np.isfinite(window)) or np.any(~np.isfinite(level_window)):
            return None
        if len(window) < 2:
            return None
        trend = float(np.polyfit(np.arange(len(window)), window, 1)[0])
        signal_last = float(window[-1])
        signal_prev = float(window[-2])
        level_last = float(level_window[-1])
        level_gap = float(level_last - level_window.mean())
        return np.array(
            [
                signal_last,
                signal_prev,
                float(window.mean()),
                float(window.std()),
                trend,
                signal_last - signal_prev,
                level_last,
                level_gap,
            ]
        )

    def fit(
        self,
        demand: np.ndarray,
        demand_level_or_market_price: np.ndarray,
        market_price: np.ndarray | None = None,
    ) -> None:
        if market_price is None:
            demand_level = demand
            market_price = demand_level_or_market_price
        else:
            demand_level = demand_level_or_market_price
        if not (len(demand) == len(demand_level) == len(market_price)):
            raise ValueError(
                "demand, demand_level, and market_price lengths must match: "
                f"{len(demand)}, {len(demand_level)}, {len(market_price)}"
            )
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(demand, demand_level, i)
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
        demand: np.ndarray,
        demand_level_or_market_price: np.ndarray,
        market_price_or_i: np.ndarray | int,
        i: int | None = None,
    ) -> tuple[float, float] | None:
        """Returns (point_price_level, log_return_score) or None.

        The v1.16 OilDemandNowcastDesk unpacks this and emits the
        log-return head as the controller-facing point_estimate (matches
        the WTI_FRONT_1W_LOG_RETURN target).
        """
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        if i is None:
            demand_level = demand
            market_price = demand_level_or_market_price
            i = int(market_price_or_i)
        else:
            demand_level = demand_level_or_market_price
            market_price = market_price_or_i
        f = self._features(demand, demand_level, i)
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


__all__ = ["ClassicalOilDemandNowcastModel"]
