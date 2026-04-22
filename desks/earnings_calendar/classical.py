"""Classical model for the earnings_calendar desk (v1.16 W10 skeleton).

Skeleton ridge on vol-surface proxies. The sim has no earnings-event
channel yet, so the head cannot access true earnings-proximity or
cluster features — it falls back to a vol-of-vol proxy computed from
the merged surface_positioning_feedback channels. Expected Gate 1/2
performance is weak until the earnings channel lands.

Follow-on scope (commission §5): structured event schema +
class-conditional impact model + state-conditioning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 10
HORIZON_DEFAULT = 3
ALPHA_DEFAULT = 1e-3


@dataclass
class ClassicalEarningsCalendarModel:
    """Skeleton ridge(vol-volatility proxy) → direct vol-delta.

    Features:
      - current vol (proxy for ATM level prior to the earnings-window)
      - trailing vol-of-vol (proxy for existing clustering / instability)
      - vol z-score vs trailing mean (proxy for stress regime)

    Intended to be replaced by a structured event-schema model once the
    sim adds an earnings channel.
    """

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(self, market_price: np.ndarray, i: int) -> np.ndarray | None:
        if i < self.lookback + 2:
            return None
        vol_window = market_price[i - self.lookback : i]
        if np.any(~np.isfinite(vol_window)):
            return None
        current_vol = max(float(vol_window[-1]), 1.0)
        vol_mean = float(vol_window.mean())
        vol_std = float(vol_window.std())
        vol_zscore = (current_vol - vol_mean) / vol_std if vol_std > 1e-6 else 0.0
        return np.array([current_vol, vol_std, vol_zscore])

    def fit(self, market_price: np.ndarray) -> None:
        if len(market_price) < self.lookback + self.horizon_days + 5:
            raise ValueError(
                f"need ≥{self.lookback + self.horizon_days + 5} prices; got {len(market_price)}"
            )
        features_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(market_price, i)
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
        market_price: np.ndarray,
        i: int,
    ) -> tuple[float, float] | None:
        """Returns (point_delta, directional_score) or None.

        point_delta is the fitted vol-delta prediction (signed, matches
        VIX_30D_FORWARD_3D_DELTA unit). directional_score equals
        point_delta — fitted-head driven, not a handcrafted heuristic.
        """
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(market_price, i)
        if f is None:
            return None
        delta_pred = float(f @ self.coef_ + self.intercept_)
        return delta_pred, delta_pred

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()


__all__ = ["ClassicalEarningsCalendarModel"]
