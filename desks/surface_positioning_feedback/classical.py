"""Classical model for the merged surface-positioning-feedback desk (v1.16).

Composite of two inlined ridge heads: one on the (dealer_flow,
vega_exposure) channel pair and one on the (hedging_demand_level,
put_skew_proxy) channel pair. Each head predicts a direct vol-delta
over the shared 3-day horizon; the composite averages their fitted
deltas at serve time.

Both heads are inlined here (was previously inherited from
desks/dealer_inventory/ + desks/hedging_demand/; those dirs are deleted
in the post-C12 cleanup wave alongside this inline). Full monotone-GAM /
GBDT rebuild is a §7.3 escalation under debit D7 per the commission at
`docs/pm/surface_positioning_feedback_engineering_commission.md`.

Emission semantics (differs from both pre-v1.16 heads):
- Point estimate is the signed **delta** (not vol level). The v1.16
  target is `VIX_30D_FORWARD_3D_DELTA`, so point_estimate must be a
  delta to keep the equity family raw-summable under
  controller/decision.py:94-112.
- Directional score is the combined fitted delta (matches point_estimate
  sign). Replaces the legacy dealer_inventory heuristic
  `flow_last + 0.25 * vega_normalized` which could disagree with the
  fitted delta.
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
class _DealerInventoryRidge:
    """Inlined ridge head on (dealer_flow, vega_exposure) channels.

    Previously lived at desks/dealer_inventory/classical.py::ClassicalDealerInventoryModel.
    Feature vector and training target unchanged.
    """

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
        market_price: np.ndarray,
        i: int,
    ) -> np.ndarray | None:
        if i < self.lookback + 2:
            return None
        flow_window = dealer_flow[i - self.lookback : i]
        vega_window = vega_exposure[i - self.lookback : i]
        vol_window = market_price[i - self.lookback : i]
        if (
            np.any(~np.isfinite(flow_window))
            or np.any(~np.isfinite(vega_window))
            or np.any(~np.isfinite(vol_window))
        ):
            return None
        if len(flow_window) < 2:
            return None
        flow_trend = float(np.polyfit(np.arange(len(flow_window)), flow_window, 1)[0])
        flow_last = float(flow_window[-1])
        flow_prev = float(flow_window[-2])
        vega_last = float(vega_window[-1])
        vega_prev = float(vega_window[-2])
        current_vol = max(float(vol_window[-1]), 1.0)
        return np.array(
            [
                flow_last,
                float(flow_window.mean()),
                flow_last - flow_prev,
                flow_trend,
                vega_last,
                float(vega_window.mean()),
                vega_last - vega_prev,
                vega_last / current_vol,
                current_vol,
                current_vol - float(vol_window.mean()),
            ]
        )

    def fit(
        self,
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        if not (len(dealer_flow) == len(vega_exposure) == len(market_price)):
            raise ValueError(
                f"inputs must share length; got {len(dealer_flow)}, "
                f"{len(vega_exposure)}, {len(market_price)}"
            )
        features_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(dealer_flow, vega_exposure, market_price, i)
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

    def predict_delta(
        self,
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> float | None:
        """Returns the fitted vol-delta prediction or None."""
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("dealer-inventory head not fitted; call .fit() first")
        f = self._features(dealer_flow, vega_exposure, market_price, i)
        if f is None:
            return None
        return float(f @ self.coef_ + self.intercept_)

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()


@dataclass
class _HedgingDemandRidge:
    """Inlined ridge head on (hedging_demand_level, put_skew_proxy) channels.

    Previously lived at desks/hedging_demand/classical.py::ClassicalHedgingDemandModel.
    Feature vector and training target unchanged.
    """

    lookback: int = 15  # hedging_demand head used a longer window
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

    def predict_delta(
        self,
        hd: np.ndarray,
        skew: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> float | None:
        """Returns the fitted vol-delta prediction or None."""
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("hedging-demand head not fitted; call .fit() first")
        f = self._features(hd, skew, market_price, i)
        if f is None:
            return None
        return float(f @ self.coef_ + self.intercept_)

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()


@dataclass
class ClassicalSurfacePositioningFeedbackModel:
    """Composite ridge over both (dealer, hedging) channel sets.

    Each head fits independently on its own 10-feature channel set and
    predicts a vol-delta over the shared 3-day horizon. The composite
    averages their fitted deltas at serve time.
    """

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    _dealer: _DealerInventoryRidge = field(init=False)
    _hedging: _HedgingDemandRidge = field(init=False)

    def __post_init__(self) -> None:
        self._dealer = _DealerInventoryRidge(
            lookback=self.lookback,
            horizon_days=self.horizon_days,
            alpha=self.alpha,
        )
        # Hedging head preserves the longer 15-day lookback from its legacy
        # configuration (> 2× hd process half-life at hd_ar1=0.9).
        self._hedging = _HedgingDemandRidge(
            horizon_days=self.horizon_days,
            alpha=self.alpha,
        )

    def fit(
        self,
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        hedging_demand_level: np.ndarray,
        put_skew_proxy: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        self._dealer.fit(dealer_flow, vega_exposure, market_price)
        self._hedging.fit(hedging_demand_level, put_skew_proxy, market_price)

    def predict(
        self,
        dealer_flow: np.ndarray,
        vega_exposure: np.ndarray,
        hedging_demand_level: np.ndarray,
        put_skew_proxy: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> tuple[float, float] | None:
        """Returns (point_delta, directional_score) or None.

        point_delta: signed averaged vol-delta prediction over the shared
        horizon. directional_score matches the delta sign (fitted head,
        not the legacy handcrafted heuristic).
        """
        d_delta = self._dealer.predict_delta(dealer_flow, vega_exposure, market_price, i)
        h_delta = self._hedging.predict_delta(
            hedging_demand_level, put_skew_proxy, market_price, i
        )
        if d_delta is None or h_delta is None:
            return None
        current_vol = float(market_price[i - 1])
        if current_vol <= 0:
            return None
        combined_delta = 0.5 * (float(d_delta) + float(h_delta))
        return combined_delta, combined_delta

    def fingerprint(self) -> str:
        df = self._dealer.fingerprint()
        hf = self._hedging.fingerprint()
        joined = (df + "|" + hf).encode("utf-8")
        return "sha256:" + hashlib.sha256(joined).hexdigest()


__all__ = ["ClassicalSurfacePositioningFeedbackModel"]
