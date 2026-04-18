"""Dealer-inventory desk — equity-VRP Phase 2 MVP (spec v1.12).

Analogue to the oil storage_curve desk: load-bearing portability
proof. Consumes sim_equity_vrp's per-desk channels and emits a
Forecast targeting VIX_30D_FORWARD.

Composition mirror of supply/demand/geopolitics/macro desks:
  DealerInventoryDesk() with no model → stub behaviour (null signal).
  DealerInventoryDesk(model=ClassicalDealerInventoryModel()) → ridge-
    based point estimate + positive directional claim.

Hot-swap (Gate 3) is preserved: the Controller can replace this desk
with a generic StubDesk at any time; both satisfy DeskProtocol.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from contracts.target_variables import VIX_30D_FORWARD
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from desks.base import StubDesk

from .classical import ClassicalDealerInventoryModel

if TYPE_CHECKING:
    import duckdb

    from sim_equity_vrp.observations import EquityObservationChannels


class DealerInventoryDesk(StubDesk):
    name: str = "dealer_inventory"
    spec_path: str = "desks/dealer_inventory/spec.md"
    target_variable: str = VIX_30D_FORWARD
    event_id: str = "vix_settle"
    horizon_days: int = 3
    feed_names: list[str] = ["vix_eod"]

    def __init__(self, model: ClassicalDealerInventoryModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_dealer_inventory",
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
        dealer_flow = channels.by_desk[self.name].components["dealer_flow"]
        vega_exposure = channels.by_desk[self.name].components["vega_exposure"]
        pred = self.model.predict(dealer_flow, vega_exposure, channels.market_price, i)
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
            uncertainty=UncertaintyInterval(
                level=0.8,
                lower=max(point - 2.0, 0.0),
                upper=point + 2.0,
            ),
            directional_claim=DirectionalClaim(
                variable=self.target_variable,
                sign="positive",
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
        dealer_flow = channels.by_desk[self.name].components["dealer_flow"]
        vega_exposure = channels.by_desk[self.name].components["vega_exposure"]
        pred = self.model.predict(dealer_flow, vega_exposure, channels.market_price, i)
        if pred is None:
            return None
        return pred[1]
