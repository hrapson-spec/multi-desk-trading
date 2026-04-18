"""Classical specialist for the hedging_demand desk (Phase 2 v1.13).

Predicts next-period vol level from compact statistics of the
hedging_demand + put_skew_proxy observation channels. The current
feature vector mixes level, change, trend, vol-normalized skew pressure,
and simple vol context so the model learns a direct vol-delta rather
than a tiny log-return.

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
    """Ridge(hd + skew features) → direct vol-delta → vol."""

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
        market_price: np.ndarray,
        i: int,
    ) -> np.ndarray | None:
        """Hedging/skew features for direct vol-delta prediction."""
        if i < self.lookback + 2:
            return None
        hd_window = hd[i - self.lookback : i]
        skew_window = skew[i - self.lookback : i]
        vol_window = market_price[i - self.lookback : i]
        if (
            np.any(~np.isfinite(hd_window))
            or np.any(~np.isfinite(skew_window))
            or np.any(~np.isfinite(vol_window))
        ):
            return None
        if len(hd_window) < 2:
            return None
        hd_trend = float(np.polyfit(np.arange(len(hd_window)), hd_window, 1)[0])
        hd_last = float(hd_window[-1])
        hd_prev = float(hd_window[-2])
        skew_last = float(skew_window[-1])
        skew_prev = float(skew_window[-2])
        current_vol = max(float(vol_window[-1]), 1.0)
        return np.array(
            [
                hd_last,
                float(hd_window.mean()),
                hd_last - hd_prev,
                hd_trend,
                skew_last,
                float(skew_window.mean()),
                skew_last - skew_prev,
                skew_last / current_vol,
                current_vol,
                current_vol - float(vol_window.mean()),
            ]
        )

    def fit(
        self,
        hd: np.ndarray,
        skew: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        """Build (features at i, future_vol - current_vol) pairs and fit ridge.

        M-1: callers should pass NOISY observation channels (not clean
        latent) so train distribution matches serve distribution."""
        if not (len(hd) == len(skew) == len(market_price)):
            raise ValueError(
                f"inputs must share length; got {len(hd)}, {len(skew)}, {len(market_price)}"
            )
        features_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(hd, skew, market_price, i)
            if f is None:
                continue
            future_vol = float(market_price[i + self.horizon_days])
            current_vol = float(market_price[i - 1])
            if current_vol <= 0:
                continue
            features_list.append(f)
            y_list.append(float(future_vol - current_vol))
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
        directional_score is the leading hedging-pressure signal."""
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(hd, skew, market_price, i)
        if f is None:
            return None
        delta_pred = float(f @ self.coef_ + self.intercept_)
        current_vol = float(market_price[i - 1])
        if current_vol <= 0:
            return None
        point = current_vol + delta_pred
        # Use the leading hedging-pressure signal as the directional score.
        directional_score = float(f[0] + 0.25 * f[7])
        return point, directional_score

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()
