"""Real-time synthetic data feed for the Reliability-gate runner
(plan fix 3).

Wraps a `sim.LatentPath` and exposes a `tick(state)` method the
SoakRunner calls once per cadence interval. Each tick:

  1. Emits a Forecast per desk via the bus (desks pass through the
     stub path; the soak run exercises bus+persistence write paths,
     not desk alpha).
  2. Asks the supplied regime classifier for a RegimeLabel.
  3. Invokes Controller.decide and publishes the Decision.
  4. Increments state.sim_day_index and state.n_decisions_emitted.

This is a WRITE-PATH exercise: forecasts, prints, regime labels,
decisions, controller-params reads, signal-weights reads. It does NOT
run attribution per tick — at production cadence (1 sim-day/min) that
would dominate. A higher-level scheduler calls LODO/Shapley at the
periodic review cadence, matching the real architecture.

Determinism: the feed is seed-deterministic given the LatentPath; the
runner may pass fresh RNG where the bus/persistence layers need it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller
from persistence import insert_decision, insert_forecast
from sim.observations import ObservationChannels

from .checkpoint import SoakState


@runtime_checkable
class _RegimeClassifierProtocol(Protocol):
    """Structural interface the soak feed needs from any classifier.

    Keeps soak/ free of any `desks.*` import (§8.4 portability — Phase 2
    redeployment uses equity-VRP desks). Any class with a matching
    `regime_label_at` signature satisfies this.
    """

    def regime_label_at(
        self, channels: ObservationChannels, i: int, now_utc: datetime
    ) -> RegimeLabel: ...


@dataclass
class SyntheticDataFeed:
    """Stateless driver: each tick advances state.sim_day_index by 1."""

    channels: ObservationChannels
    controller: Controller
    classifier: _RegimeClassifierProtocol
    desks: tuple[str, ...] = (
        "storage_curve",
        "supply",
        "demand",
        "geopolitics",
        "macro",
    )
    base_emission_ts: datetime | None = None

    def tick(self, state: SoakState) -> None:
        """Advance one sim-day, emit forecasts + decision, mutate state."""
        i = state.sim_day_index
        if i >= self.channels.latent_path.n_days:
            # Wrap-around: in a 7-day run at 1 sim-day/min with a
            # 10_000-day path, we'd run out only after ~7 days. When
            # wrap occurs, reset to day 0 — the soak test is about
            # wall-clock, not unique sim-day coverage.
            state.sim_day_index = 0
            i = 0

        base = self.base_emission_ts or datetime.fromisoformat("2026-04-16T10:00:00+00:00")
        emission_ts = base + timedelta(days=int(i))
        market_price = float(self.channels.market_price[i])

        prov = Provenance(
            desk_name="soak_feed",
            model_name="synthetic",
            model_version="0.0.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )
        # One simple forecast per desk — exercises bus + persistence.
        recent: dict[tuple[str, str], Forecast] = {}
        for desk_name in self.desks:
            f = Forecast(
                forecast_id=str(uuid.uuid4()),
                emission_ts_utc=emission_ts,
                target_variable=WTI_FRONT_MONTH_CLOSE,
                horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=emission_ts),
                point_estimate=market_price,
                uncertainty=UncertaintyInterval(
                    level=0.8, lower=market_price - 5.0, upper=market_price + 5.0
                ),
                directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
                staleness=False,
                confidence=0.7,
                provenance=prov.model_copy(update={"desk_name": desk_name}),
            )
            recent[(desk_name, WTI_FRONT_MONTH_CLOSE)] = f

        # Persist forecasts — exercises the write path that a real bus
        # would handle. The soak test doesn't go through Bus because
        # re-registering handlers on each restart is orthogonal to the
        # endurance test; direct inserts exercise the same DB pressure.
        for f in recent.values():
            insert_forecast(self.controller.conn, f)

        # Classify regime using ground truth (cheap — the soak test
        # doesn't exercise the HMM; that's a separate benchmark).
        label = self.classifier.regime_label_at(self.channels, i, emission_ts)

        # Controller decides — this is the load-bearing write path.
        decision = self.controller.decide(
            now_utc=emission_ts,
            regime_label=label,
            recent_forecasts=recent,
        )
        insert_decision(self.controller.conn, decision)

        state.sim_day_index = i + 1
        state.n_decisions_emitted += 1
