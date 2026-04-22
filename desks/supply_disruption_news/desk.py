"""Merged supply-disruption-news desk (v1.16).

Event-hurdle framing per `docs/first_principles_redesign.md` and
`docs/pm/supply_disruption_news_engineering_commission.md`. Activation
probability times conditional effect size. Emits near-zero outside activated
states.

Reads from the sim `geopolitics` channel for the ridge head (primary event
intensity + balance-state signal). The `supply` channel is additionally
available via the sim and can be routed into internal auxiliary labels in the
full mechanism rebuild (§7.3 escalation). For Phase 2 scale-out the ridge head
mirrors the pre-v1.16 `disruption_risk` WIP behaviour under the new name.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

from contracts.target_variables import WTI_FRONT_1W_LOG_RETURN
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from desks.base import StubDesk

from .classical import ClassicalSupplyDisruptionNewsModel

if TYPE_CHECKING:
    import duckdb

    from sim.observations import ObservationChannels


def _derive_sign(score: float) -> Literal["positive", "negative", "none"]:
    if score > 1e-6:
        return "positive"
    if score < -1e-6:
        return "negative"
    return "none"


class SupplyDisruptionNewsDesk(StubDesk):
    name: str = "supply_disruption_news"
    spec_path: str = "desks/supply_disruption_news/spec.md"
    target_variable: str = WTI_FRONT_1W_LOG_RETURN
    event_id: str = "opec_announcement"
    horizon_days: int = 7
    feed_names: list[str] = ["opec_announcement", "eia_wpsr"]

    def __init__(self, model: ClassicalSupplyDisruptionNewsModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="supply_disruption_news_v0",
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
        obs = channels.by_desk["geopolitics"].components
        balance = obs.get("balance_state", obs["event_intensity_raw"])
        score = self.model.predict_return(
            obs["event_indicator"],
            obs["event_intensity"],
            obs["event_intensity_raw"],
            channels.market_price,
            i,
            balance_state=balance,
        )
        if score is None:
            return self._build_stub_forecast(now_utc)
        stale = conn is not None and self._staleness_from_feeds(conn)
        spread = max(0.01, 2.5 * abs(float(score)))
        return Forecast(
            forecast_id=str(uuid.uuid4()),
            emission_ts_utc=now_utc,
            target_variable=self.target_variable,
            horizon=EventHorizon(
                event_id=self.event_id,
                expected_ts_utc=now_utc + timedelta(days=self.horizon_days),
            ),
            point_estimate=float(score),
            uncertainty=UncertaintyInterval(
                level=0.8,
                lower=float(score) - spread,
                upper=float(score) + spread,
            ),
            directional_claim=DirectionalClaim(
                variable=self.target_variable,
                sign=_derive_sign(float(score)),
            ),
            staleness=stale,
            confidence=0.65,
            provenance=self._provenance_classical(),
        )

    def directional_score(self, channels: ObservationChannels, i: int) -> float | None:
        if self.model is None:
            return None
        obs = channels.by_desk["geopolitics"].components
        balance = obs.get("balance_state", obs["event_intensity_raw"])
        return self.model.predict_return(
            obs["event_indicator"],
            obs["event_intensity"],
            obs["event_intensity_raw"],
            channels.market_price,
            i,
            balance_state=balance,
        )
