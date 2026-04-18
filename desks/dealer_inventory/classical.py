"""Classical specialist for the dealer_inventory desk (Phase 2 MVP).

Predicts next-period vol level from compact statistics of the
dealer_flow + vega_exposure channels. Ridge over [dealer_flow_last,
dealer_flow_mean, dealer_flow_trend, vega_last, vega_mean].

Equity-VRP economic intuition: when dealers get short vol (positive
dealer_flow in this sim's convention), they hedge by buying vol
products → next-period realised/implied vol tends up. The
correlation is baked into `sim_equity_vrp.latent_state` (flow_vol_corr
= 0.35 by default).

Capability-claim debit mirror of oil's ridge-on-4-features debit
(D1): this is a deliberately modest model. The architectural test is
whether the desk emits valid Forecasts that pass the three hard
gates and compose with LODO/Shapley, not whether the ridge is
optimal.
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
class ClassicalDealerInventoryModel:
    """Ridge(dealer-flow + vega features) → log-return-of-vol → vol."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(
        self,
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        i: int,
    ) -> np.ndarray | None:
        """Per-timestep feature vector: last/mean/trend of flow +
        last/mean of vega exposure."""
        if i < self.lookback + 1:
            return None
        flow_window = dealer_flow[i - self.lookback : i]
        vega_window = vega_exposure[i - self.lookback : i]
        if np.any(~np.isfinite(flow_window)) or np.any(~np.isfinite(vega_window)):
            return None
        if len(flow_window) < 2:
            return None
        trend = float(np.polyfit(np.arange(len(flow_window)), flow_window, 1)[0])
        return np.array(
            [
                float(flow_window[-1]),
                float(flow_window.mean()),
                trend,
                float(vega_window[-1]),
                float(vega_window.mean()),
            ]
        )

    def fit(
        self,
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        """Build (features at i, log-return-of-vol over horizon) pairs
        and fit ridge. market_price is the vol_level series per
        sim_equity_vrp.observations.EquityObservationChannels."""
        if not (len(dealer_flow) == len(vega_exposure) == len(market_price)):
            raise ValueError(
                f"inputs must share length; got {len(dealer_flow)}, "
                f"{len(vega_exposure)}, {len(market_price)}"
            )
        features_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(dealer_flow, vega_exposure, i)
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
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> tuple[float, float] | None:
        """Returns (point_estimate_vol, directional_score) or None."""
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(dealer_flow, vega_exposure, i)
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
