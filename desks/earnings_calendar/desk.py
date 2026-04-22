"""Earnings-calendar desk (v1.16 W10 skeleton).

Event-driven equity-VRP desk. Emits `VIX_30D_FORWARD_3D_DELTA` — same
shared unit as surface_positioning_feedback — so the Controller's
raw-sum aggregation at `controller/decision.py:94-112` stays unit-
consistent across the equity family.

W10 skeleton: reads only vol-level proxies from the merged
surface_positioning_feedback channels. The real alpha mechanism
(earnings-proximity, clustering, sector weight) requires an earnings
channel in the sim which is a follow-on wave.
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

from .classical import ClassicalEarningsCalendarModel

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


class EarningsCalendarDesk(StubDesk):
    name: str = "earnings_calendar"
    spec_path: str = "desks/earnings_calendar/spec.md"
    target_variable: str = VIX_30D_FORWARD_3D_DELTA
    event_id: str = "earnings_cluster"
    horizon_days: int = 3
    feed_names: list[str] = ["earnings_calendar_feed", "vix_eod"]

    def __init__(self, model: ClassicalEarningsCalendarModel | None = None):
        self.model = model

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="skeleton_earnings_calendar",
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def _read_earnings_channels(
        self, channels: EquityObservationChannels
    ) -> tuple:
        obs = channels.by_desk["earnings_calendar"].components
        return (
            obs["earnings_event_indicator"],
            obs["earnings_cluster_size"],
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
        indicator, cluster_size = self._read_earnings_channels(channels)
        pred = self.model.predict(indicator, cluster_size, channels.market_price, i)
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
            confidence=0.55,
            provenance=self._provenance_classical(),
        )

    def directional_score(
        self,
        channels: EquityObservationChannels,
        i: int,
    ) -> float | None:
        if self.model is None:
            return None
        indicator, cluster_size = self._read_earnings_channels(channels)
        pred = self.model.predict(indicator, cluster_size, channels.market_price, i)
        if pred is None:
            return None
        return float(pred[1])
