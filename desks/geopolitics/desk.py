"""Geopolitics & Risk desk (plan §A; spec §5.3).

Consumes event_indicator + event_intensity channels; predicts price via
the Hawkes-feature ridge. See ClassicalGeopoliticsModel for feature
construction and the Phase A debit on LLM event extraction.
"""

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

from .classical import ClassicalGeopoliticsModel

if TYPE_CHECKING:
    import duckdb

    from sim.observations import ObservationChannels


class GeopoliticsDesk(StubDesk):
    name: str = "geopolitics"
    spec_path: str = "desks/geopolitics/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7
    feed_names: list[str] = ["opec_announcement"]

    def __init__(self, model: ClassicalGeopoliticsModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_geopolitics",
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
        obs = channels.by_desk[self.name].components
        pred = self.model.predict(
            obs["event_indicator"],
            obs["event_intensity"],
            obs["event_intensity_raw"],
            channels.market_price,
            i,
        )
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
        obs = channels.by_desk[self.name].components
        pred = self.model.predict(
            obs["event_indicator"],
            obs["event_intensity"],
            obs["event_intensity_raw"],
            channels.market_price,
            i,
        )
        if pred is None:
            return None
        return pred[1]
