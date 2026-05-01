"""Merged surface-positioning-feedback desk (v1.16).

Absorbs `dealer_inventory` + `hedging_demand` per the adopted pasted review in
`docs/first_principles_redesign.md`. Reads BOTH legacy channel keys
(`by_desk["dealer_inventory"]` for dealer_flow + vega_exposure,
`by_desk["hedging_demand"]` for hedging_demand_level + put_skew_proxy) until
C9 collapses them into one `by_desk["surface_positioning_feedback"]` key.

Emits `VIX_30D_FORWARD_3D_DELTA` (new v1.16 target; added to
`contracts/target_variables.py` at C2). The emission is a **signed 3-day vol
delta**, not a vol level — this keeps the equity family on a single
decision-space unit that `controller/decision.py:94-112` can raw-sum across
desks (the legacy `VIX_30D_FORWARD` level target was unit-incompatible once
more than one equity desk joined the roster).

Internal auxiliary label `next_session_rv_surprise` is planned (see C11,
which adds a decision-time `fair_vol_baseline` channel to
`EquityObservationChannels`). Until then the desk consumes only the merged
flow + skew channels.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from contracts.target_variables import VIX_30D_FORWARD_3D_DELTA
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from desks.base import StubDesk

from .classical import ClassicalSurfacePositioningFeedbackModel

if TYPE_CHECKING:
    import duckdb

    from sim_equity_vrp.observations import EquityObservationChannels

_SIGN_EPSILON = 1e-6


def _derive_sign(score: float) -> Literal["positive", "negative", "none"]:
    if score > _SIGN_EPSILON:
        return "positive"
    if score < -_SIGN_EPSILON:
        return "negative"
    return "none"


class SurfacePositioningFeedbackDesk(StubDesk):
    name: str = "surface_positioning_feedback"
    spec_path: str = "desks/surface_positioning_feedback/spec.md"
    target_variable: str = VIX_30D_FORWARD_3D_DELTA
    event_id: str = "vix_settle"
    horizon_days: int = 3
    feed_names: list[str] = ["vix_eod", "cboe_open_interest", "option_volume"]

    def __init__(self, model: ClassicalSurfacePositioningFeedbackModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_surface_positioning_feedback",
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def _read_channels(self, channels: EquityObservationChannels) -> tuple:
        """Read the four component arrays from whichever legacy or merged
        key is present in the observation layer.

        C8-era: `by_desk["dealer_inventory"]` and `by_desk["hedging_demand"]`
        still coexist. C9 collapses them into `by_desk["surface_positioning_feedback"]`
        with the same four component names; this helper reads whichever is
        present.
        """
        if self.name in channels.by_desk:
            merged = channels.by_desk[self.name].components
            return (
                merged["dealer_flow"],
                merged["vega_exposure"],
                merged["hedging_demand_level"],
                merged["put_skew_proxy"],
            )
        dealer = channels.by_desk["dealer_inventory"].components
        hedging = channels.by_desk["hedging_demand"].components
        return (
            dealer["dealer_flow"],
            dealer["vega_exposure"],
            hedging["hedging_demand_level"],
            hedging["put_skew_proxy"],
        )

    def forecast_from_observation(
        self,
        channels: EquityObservationChannels,
        i: int,
        now_utc: datetime,
        *,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> Forecast:
        if self.model is None:
            return self._build_stub_forecast(now_utc)
        dealer_flow, vega_exposure, hd_level, skew = self._read_channels(channels)
        pred = self.model.predict(
            dealer_flow, vega_exposure, hd_level, skew, channels.market_price, i
        )
        if pred is None:
            return self._build_stub_forecast(now_utc)
        point, score = pred
        stale = conn is not None and self._staleness_from_feeds(conn)
        spread = max(0.5, 2.0 * abs(float(point)))
        return Forecast(
            forecast_id=str(uuid.uuid4()),
            emission_ts_utc=now_utc,
            target_variable=self.target_variable,
            horizon=EventHorizon(
                event_id=self.event_id,
                expected_ts_utc=now_utc + timedelta(days=self.horizon_days),
            ),
            point_estimate=float(point),
            uncertainty=UncertaintyInterval(
                level=0.8,
                lower=float(point) - spread,
                upper=float(point) + spread,
            ),
            directional_claim=DirectionalClaim(
                variable=self.target_variable,
                sign=_derive_sign(float(score)),
            ),
            staleness=stale,
            confidence=0.7,
            provenance=self._provenance_classical(),
        )

    def directional_score(
        self,
        channels: EquityObservationChannels,
        i: int,
    ) -> float | None:
        if self.model is None:
            return None
        dealer_flow, vega_exposure, hd_level, skew = self._read_channels(channels)
        pred = self.model.predict(
            dealer_flow, vega_exposure, hd_level, skew, channels.market_price, i
        )
        if pred is None:
            return None
        return float(pred[1])
