"""Classical model for the earnings_calendar desk (v1.16 X1).

Reads the `earnings_event_indicator` + `earnings_cluster_size` channels
from `sim_equity_vrp.observations.EquityObservationChannels.by_desk
["earnings_calendar"]`. Ridge on 5 features → fitted vol-delta
prediction.

Feature vector at time t:
  - earnings_cluster_size[t]   : count of events in the trailing
    cluster_window days (primary mechanism feature)
  - earnings_event_indicator[t]: 0/1 today-is-event flag
  - event_density              : trailing-`lookback` mean of the indicator
  - current_vol                : market_price[t-1]
  - vol_zscore                 : (current_vol - trailing_mean) / trailing_std

Mechanism: the sim generates earnings with a forward-correlation to
vol_shocks at t+2 (lead=2), so earnings_cluster_size[t] has a real,
learnable predictive relationship with vol_level[t+3] (horizon_days=3).

Previous v1.16 W10 skeleton read only vol-level proxies — no alpha by
design. D-17 closed at X1.
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
    """Ridge(earnings + vol features) → direct vol-delta."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(
        self,
        earnings_event_indicator: np.ndarray,
        earnings_cluster_size: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> np.ndarray | None:
        if i < self.lookback + 2:
            return None
        vol_window = market_price[i - self.lookback : i]
        ind_window = earnings_event_indicator[i - self.lookback : i]
        if np.any(~np.isfinite(vol_window)):
            return None
        current_vol = max(float(vol_window[-1]), 1.0)
        vol_mean = float(vol_window.mean())
        vol_std = float(vol_window.std())
        vol_zscore = (current_vol - vol_mean) / vol_std if vol_std > 1e-6 else 0.0
        cluster_size = float(earnings_cluster_size[i])
        event_today = float(earnings_event_indicator[i])
        event_density = float(ind_window.mean())
        return np.array(
            [
                cluster_size,
                event_today,
                event_density,
                current_vol,
                vol_zscore,
            ]
        )

    def fit(
        self,
        earnings_event_indicator: np.ndarray,
        earnings_cluster_size: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        if not (
            len(earnings_event_indicator)
            == len(earnings_cluster_size)
            == len(market_price)
        ):
            raise ValueError(
                "inputs must share length; got "
                f"{len(earnings_event_indicator)}, "
                f"{len(earnings_cluster_size)}, {len(market_price)}"
            )
        features_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(
                earnings_event_indicator, earnings_cluster_size, market_price, i
            )
            if f is None:
                continue
            future_vol = float(market_price[i + self.horizon_days])
            current_vol = float(market_price[i - 1])
            if current_vol <= 0:
                continue
            features_list.append(f)
            y_list.append(float(future_vol - current_vol))
        if len(features_list) < 5:
            raise ValueError(
                f"insufficient training rows: got {len(features_list)}; need ≥5"
            )

        feature_mat = np.asarray(features_list, dtype=float)
        target = np.asarray(y_list, dtype=float)
        coef, intercept = fit_ridge(feature_mat, target, alpha=self.alpha)
        self.coef_ = coef
        self.intercept_ = intercept
        self.n_train_ = len(features_list)

    def predict(
        self,
        earnings_event_indicator: np.ndarray,
        earnings_cluster_size: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> tuple[float, float] | None:
        """Returns (point_delta, directional_score) or None.

        point_delta is the fitted vol-delta (signed, matches the
        VIX_30D_FORWARD_3D_DELTA emission unit). directional_score
        equals point_delta — fitted-head driven, not a heuristic.
        """
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(
            earnings_event_indicator, earnings_cluster_size, market_price, i
        )
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
