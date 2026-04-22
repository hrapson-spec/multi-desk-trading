"""Classical model for the merged surface-positioning-feedback desk (v1.16).

Composite of the pre-v1.16 `ClassicalDealerInventoryModel` and
`ClassicalHedgingDemandModel`. Both inherited-model ridges stay intact;
the composite fits each on its own channel set and averages their fitted
delta predictions at serve time. Phase 2 scale-out quality floor; the full
monotone-GAM / GBDT rebuild is a §7.3 escalation under debit D7 per the
commission at `docs/pm/surface_positioning_feedback_engineering_commission.md`.

Emission semantics — differs from the pre-v1.16 desks:
- Point estimate is the signed **delta** (not vol level). The target is
  `VIX_30D_FORWARD_3D_DELTA`, so the point_estimate must be a delta.
- Directional score matches the fitted delta sign (not a hand-built
  heuristic like the legacy `flow_last + 0.25 * vega_normalized`).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.dealer_inventory.classical import (
    ALPHA_DEFAULT,
    HORIZON_DEFAULT,
    LOOKBACK_DEFAULT,
    ClassicalDealerInventoryModel,
)
from desks.hedging_demand.classical import ClassicalHedgingDemandModel


@dataclass
class ClassicalSurfacePositioningFeedbackModel:
    """Composite ridge over both (dealer, hedging) channel sets.

    Keeps each channel's feature engineering inside its original classical
    model (to minimise code duplication and preserve any design-review
    fixes from those heads). The composite averages their fitted deltas to
    produce the emitted signed 3-day vol delta.
    """

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    _dealer: ClassicalDealerInventoryModel = field(init=False)
    _hedging: ClassicalHedgingDemandModel = field(init=False)

    def __post_init__(self) -> None:
        self._dealer = ClassicalDealerInventoryModel(
            lookback=self.lookback,
            horizon_days=self.horizon_days,
            alpha=self.alpha,
        )
        self._hedging = ClassicalHedgingDemandModel(
            lookback=self.lookback,
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
        horizon. Directional score matches the delta sign (the fitted head
        drives both, unlike the legacy dealer_inventory heuristic).
        """
        dpred = self._dealer.predict(dealer_flow, vega_exposure, market_price, i)
        hpred = self._hedging.predict(hedging_demand_level, put_skew_proxy, market_price, i)
        if dpred is None or hpred is None:
            return None
        current_vol = float(market_price[i - 1])
        if current_vol <= 0:
            return None
        # ClassicalDealerInventoryModel.predict returns (point_vol_level, score).
        # ClassicalHedgingDemandModel.predict returns (point_vol_level, score).
        # Convert both to deltas by subtracting current vol, then average.
        d_delta = float(dpred[0]) - current_vol
        h_delta = float(hpred[0]) - current_vol
        combined_delta = 0.5 * (d_delta + h_delta)
        # Fitted-delta-head directional score: use the combined delta itself
        # (not a handcrafted heuristic). Preserves sign consistency between
        # point_estimate and directional_claim.
        return combined_delta, combined_delta

    def fingerprint(self) -> str:
        df = self._dealer.fingerprint()
        hf = self._hedging.fingerprint()
        joined = (df + "|" + hf).encode("utf-8")
        return "sha256:" + hashlib.sha256(joined).hexdigest()


__all__ = ["ClassicalSurfacePositioningFeedbackModel"]
