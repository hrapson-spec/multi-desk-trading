"""Storage & Curve desk — classical-specialist deepen (Week 3 per plan §12.1).

Composition model:
  - StorageCurveDesk() with no model → stub behaviour (see StubDesk).
  - StorageCurveDesk(model=ClassicalStorageCurveModel()) → emits ridge-based
    point estimates + positive directional claim; staleness=False; the
    directional-score getter feeds Gate 2 sign-preservation.

Hot-swap (Gate 3) is preserved: the Controller can replace this desk with a
StubDesk at any time; both satisfy the DeskProtocol.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import numpy as np

from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from desks.base import StubDesk

from .classical import ClassicalStorageCurveModel

if TYPE_CHECKING:
    import duckdb

    from sim.observations import ObservationChannels


class StorageCurveDesk(StubDesk):
    name: str = "storage_curve"
    spec_path: str = "desks/storage_curve/spec.md"
    event_id: str = "cftc_cot"
    horizon_days: int = 7
    feed_names: list[str] = ["eia_wpsr", "cftc_cot"]

    def __init__(self, model: ClassicalStorageCurveModel | None = None):
        # StubDesk has no __init__; we introduce one to accept an optional
        # fitted model. None → falls back to stub emission (sign="none").
        self.model = model

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    def _provenance_classical(self) -> Provenance:
        fp = (self.model.fingerprint() if self.model else "unfit").encode("utf-8").hex()
        # Pad/truncate the fingerprint to satisfy input_snapshot_hash length
        # (64-char hex per Provenance invariant); this is a synthetic-regime
        # stand-in for the canonical ingest-snapshot hash.
        snapshot_hash = (fp + "0" * 64)[:64]
        return Provenance(
            desk_name=self.name,
            model_name="ridge_storage_curve",
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    # ------------------------------------------------------------------
    # Price-driven emission (deepen-phase interface)
    # ------------------------------------------------------------------

    def forecast_from_prices(
        self,
        prices: np.ndarray,
        i: int,
        now_utc: datetime,
        *,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> Forecast:
        """Emit a Forecast using prices[:i] and the fitted classical model.

        Falls back to the stub Forecast when the model is absent or when the
        feature window doesn't fit (early in a history).
        """
        if self.model is None:
            return self._build_stub_forecast(now_utc)
        pred = self.model.predict(prices, i)
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

    def directional_score(self, prices: np.ndarray, i: int) -> float | None:
        """Signed predicted return at index i; Gate 2 input.

        Returns None if the model is unfit or the history is too short.
        """
        if self.model is None:
            return None
        pred = self.model.predict(prices, i)
        if pred is None:
            return None
        return pred[1]

    # ------------------------------------------------------------------
    # Observation-driven emission (Phase A shared-latent simulator)
    # ------------------------------------------------------------------
    #
    # Phase A tests use ObservationChannels as the unified input surface
    # for every desk. Storage & Curve's natural channel is the noisy
    # market_price + balance observation; the existing classical model is
    # price-only, so we feed it the market_price stream directly.

    def forecast_from_observation(
        self,
        channels: ObservationChannels,
        i: int,
        now_utc: datetime,
        *,
        conn: duckdb.DuckDBPyConnection | None = None,
    ) -> Forecast:
        return self.forecast_from_prices(np.asarray(channels.market_price), i, now_utc, conn=conn)

    def directional_score_from_observation(
        self, channels: ObservationChannels, i: int
    ) -> float | None:
        return self.directional_score(np.asarray(channels.market_price), i)
