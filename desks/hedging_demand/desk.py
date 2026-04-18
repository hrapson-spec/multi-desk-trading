"""Hedging-demand desk — equity-VRP Phase 2 scale-out (spec v1.13).

Analogue to the oil `supply` desk. Consumes equity-vol observation
channels (hedging_demand_level + put_skew_proxy) and forecasts
VIX_30D_FORWARD.

M-3 fix from design review: `directional_claim.sign` is DERIVED from
the ridge score, not hardcoded. A ridge model emits signed predictions
over log-return of vol; hardcoding sign="positive" while the score
occasionally goes negative produces internally-incoherent Forecasts.
Threshold: |score| < 1e-6 → "none"; > 0 → "positive"; < 0 → "negative".

M-1 fix: the desk reads NOISY observation channels at serve time;
callers of `ClassicalHedgingDemandModel.fit()` should pass the same
noisy channels (not `latent_path.hedging_demand`) so train/serve
distributions match.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from contracts.target_variables import VIX_30D_FORWARD
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from desks.base import StubDesk

from .classical import ClassicalHedgingDemandModel

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


class HedgingDemandDesk(StubDesk):
    name: str = "hedging_demand"
    spec_path: str = "desks/hedging_demand/spec.md"
    target_variable: str = VIX_30D_FORWARD
    event_id: str = "cboe_eod"
    horizon_days: int = 3
    feed_names: list[str] = ["cboe_open_interest", "option_volume"]

    def __init__(self, model: ClassicalHedgingDemandModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_hedging_demand",
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
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
        hd_obs = channels.by_desk[self.name].components["hedging_demand_level"]
        skew_obs = channels.by_desk[self.name].components["put_skew_proxy"]
        pred = self.model.predict(hd_obs, skew_obs, channels.market_price, i)
        if pred is None:
            return self._build_stub_forecast(now_utc)
        point, score = pred
        stale = conn is not None and self._staleness_from_feeds(conn)
        sign = _derive_sign(score)
        return Forecast(
            forecast_id=str(uuid.uuid4()),
            emission_ts_utc=now_utc,
            target_variable=self.target_variable,
            horizon=EventHorizon(
                event_id=self.event_id,
                expected_ts_utc=now_utc + timedelta(days=self.horizon_days),
            ),
            point_estimate=point,
            uncertainty=UncertaintyInterval(
                level=0.8,
                lower=max(point - 2.0, 0.0),
                upper=point + 2.0,
            ),
            directional_claim=DirectionalClaim(
                variable=self.target_variable,
                sign=sign,
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
        hd_obs = channels.by_desk[self.name].components["hedging_demand_level"]
        skew_obs = channels.by_desk[self.name].components["put_skew_proxy"]
        pred = self.model.predict(hd_obs, skew_obs, channels.market_price, i)
        if pred is None:
            return None
        return pred[1]
