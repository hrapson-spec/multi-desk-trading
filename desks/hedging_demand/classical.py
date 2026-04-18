"""Classical specialist for the hedging_demand desk (Phase 2 v1.13).

Predicts next-period vol level from compact statistics of the
hedging_demand + put_skew_proxy observation channels. Ridge over
5 features: [hd_last, hd_mean, hd_trend, skew_last, skew_mean].

Economic intuition: institutional put-buying pressure raises OTM
skew AND drives next-period IV up. The correlation is baked into
`sim_equity_vrp.latent_state.EquityVolMarket` (hd_vol_corr = 0.55
by default). Real-world production would consume CBOE open-interest
+ option-volume feeds (wired in config/data_sources.yaml).

Lookback chosen as 15 days so the window > 2× hd process half-life
(~6.6 days at hd_ar1=0.9). Five summary features over the window —
the parameter name `lookback` governs the summary window, not lag
depth. Per spec.md.

Capability-claim debit mirror of oil's D1 and equity-VRP's D7: this
is a deliberately modest model. Architecture verification is Gate 3
(runtime hot-swap via eval.hot_swap.build_hot_swap_callables since
v1.14); Gates 1+2 are scale-out capability claims that may fail on
the synthetic MVP market.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 15
HORIZON_DEFAULT = 3
ALPHA_DEFAULT = 1e-3


@dataclass
class ClassicalHedgingDemandModel:
    """Ridge(hd + skew features) → log-return-of-vol → vol."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(
        self,
        hd: np.ndarray,
        skew: np.ndarray,
        i: int,
    ) -> np.ndarray | None:
        """Per-timestep feature vector: last/mean/trend of hd +
        last/mean of skew proxy."""
        if i < self.lookback + 1:
            return None
        hd_window = hd[i - self.lookback : i]
        skew_window = skew[i - self.lookback : i]
        if np.any(~np.isfinite(hd_window)) or np.any(~np.isfinite(skew_window)):
            return None
        if len(hd_window) < 2:
            return None
        trend = float(np.polyfit(np.arange(len(hd_window)), hd_window, 1)[0])
        return np.array(
            [
                float(hd_window[-1]),
                float(hd_window.mean()),
                trend,
                float(skew_window[-1]),
                float(skew_window.mean()),
            ]
        )

    def fit(
        self,
        hd: np.ndarray,
        skew: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        """Build (features at i, log-return-of-vol over horizon) pairs
        and fit ridge. market_price is the vol_level series.

        M-1: callers should pass NOISY observation channels (not clean
        latent) so train distribution matches serve distribution."""
        if not (len(hd) == len(skew) == len(market_price)):
            raise ValueError(
                f"inputs must share length; got {len(hd)}, {len(skew)}, {len(market_price)}"
            )
        features_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(hd, skew, i)
            if f is None:
                continue
            future_vol = float(market_price[i + self.horizon_days])
            current_vol = float(market_price[i - 1])
            if current_vol <= 0 or future_vol <= 0:
                continue
            log_ret = float(np.log(future_vol) - np.log(current_vol))
            features_list.append(f)
            y_list.append(log_ret)
        if len(features_list) < 5:
            raise ValueError(f"insufficient training rows: got {len(features_list)}; need ≥5")

        feature_mat = np.asarray(features_list, dtype=float)
        target = np.asarray(y_list, dtype=float)
        coef, intercept = fit_ridge(feature_mat, target, alpha=self.alpha)
        self.coef_ = coef
        self.intercept_ = intercept
        self.n_train_ = len(features_list)

    def predict(
        self,
        hd: np.ndarray,
        skew: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> tuple[float, float] | None:
        """Returns (point_estimate_vol, directional_score) or None.
        directional_score is the predicted log-return of vol."""
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(hd, skew, i)
        if f is None:
            return None
        log_ret_pred = float(f @ self.coef_ + self.intercept_)
        current_vol = float(market_price[i - 1])
        if current_vol <= 0:
            return None
        point = current_vol * float(np.exp(log_ret_pred))
        directional_score = log_ret_pred
        return point, directional_score

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()
