"""Supply desk (plan §A; spec §5.3).

Stub and classical-specialist modes share the same DeskProtocol surface:
  - SupplyDesk() with no model → emits null-signal Forecast (see StubDesk).
  - SupplyDesk(model=ClassicalSupplyModel()) → ridge-over-supply-channel
    Forecast with sign="positive" + staleness=False.

Hot-swap (Gate 3) is preserved in either mode: Controller can replace
SupplyDesk with a StubDesk at any time without changing the interface.
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

from .classical import ClassicalSupplyModel

if TYPE_CHECKING:
    from sim.observations import ObservationChannels


class SupplyDesk(StubDesk):
    name: str = "supply"
    spec_path: str = "desks/supply/spec.md"
    event_id: str = "eia_wpsr"
    horizon_days: int = 7

    def __init__(self, model: ClassicalSupplyModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_supply",
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def forecast_from_observation(
        self, channels: ObservationChannels, i: int, now_utc: datetime
    ) -> Forecast:
        if self.model is None:
            return self._build_stub_forecast(now_utc)
        supply = channels.by_desk[self.name].components["supply"]
        pred = self.model.predict(supply, channels.market_price, i)
        if pred is None:
            return self._build_stub_forecast(now_utc)
        point, _score = pred
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
            staleness=False,
            confidence=0.7,
            provenance=self._provenance_classical(),
        )

    def directional_score(self, channels: ObservationChannels, i: int) -> float | None:
        if self.model is None:
            return None
        supply = channels.by_desk[self.name].components["supply"]
        pred = self.model.predict(supply, channels.market_price, i)
        if pred is None:
            return None
        return pred[1]
