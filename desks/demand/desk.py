"""Demand desk (plan §A; spec §5.3). Structure mirrors SupplyDesk."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from desks.base import StubDesk

from .classical import ClassicalDemandModel

if TYPE_CHECKING:
    import duckdb

    from sim.observations import ObservationChannels


class DemandDesk(StubDesk):
    name: str = "demand"
    spec_path: str = "desks/demand/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7
    feed_names: list[str] = ["eia_wpsr"]

    def __init__(self, model: ClassicalDemandModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_demand",
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def forecast_from_observation(
        self,
        channels: ObservationChannels,
        i: int,
        now_utc: datetime,
        *,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> Forecast:
        if self.model is None:
            return self._build_stub_forecast(now_utc)
        demand = channels.by_desk[self.name].components["demand"]
        pred = self.model.predict(demand, channels.market_price, i)
        if pred is None:
            return self._build_stub_forecast(now_utc)
        point, _score = pred
        stale = conn is not None and self._staleness_from_feeds(conn)
        return Forecast(
            forecast_id=str(uuid.uuid4()),
            emission_ts_utc=now_utc,
            target_variable=self.target_variable,
            horizon=EventHorizon(
                event_id=self.event_id,
                expected_ts_utc=now_utc + timedelta(days=self.horizon_days),
            ),
            point_estimate=point,
            uncertainty=UncertaintyInterval(level=0.8, lower=point - 5.0, upper=point + 5.0),
            directional_claim=DirectionalClaim(variable=self.target_variable, sign="positive"),
            staleness=stale,
            confidence=0.7,
            provenance=self._provenance_classical(),
        )

    def directional_score(self, channels: ObservationChannels, i: int) -> float | None:
        if self.model is None:
            return None
        demand = channels.by_desk[self.name].components["demand"]
        pred = self.model.predict(demand, channels.market_price, i)
        if pred is None:
            return None
        return pred[1]
