"""Desk base classes and stub implementation.

StubDesk implements the minimal §5.3 discipline: valid Forecast schema,
calibrated uncertainty wide enough to be non-skillful, directional claim
= "none", staleness = True, low confidence.

Concrete stubs subclass StubDesk and set:
  name, spec_path, target_variable, event_id (for EventHorizon)

The DeskProtocol captures the interface convention from spec §5.1 as a
runtime-checkable Protocol. Desks are not required to inherit from it,
but may use it for static typing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol, runtime_checkable

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Horizon,
    Print,
    Provenance,
    RegimeLabel,
    ResearchLoopEvent,
    UncertaintyInterval,
)


@runtime_checkable
class DeskProtocol(Protocol):
    """Spec §5.1 desk interface (forecast-emitting desks 1-5)."""

    name: str
    spec_path: str
    emit_target_variables: list[str]
    emit_horizons: list[Horizon]

    def on_schedule_fire(self, now_utc: datetime) -> list[Forecast]: ...
    def on_trigger(self, event: ResearchLoopEvent) -> list[Forecast] | None: ...


@runtime_checkable
class ClassifierProtocol(Protocol):
    """Regime classifier interface (spec §5.3 desk 6)."""

    name: str
    spec_path: str

    def on_schedule_fire(
        self, now_utc: datetime, recent_forecasts: list[Forecast]
    ) -> list[RegimeLabel]: ...


# ---------------------------------------------------------------------------
# StubDesk — valid boundary contract, null signal
# ---------------------------------------------------------------------------


class StubDesk:
    """Minimal stub conforming to DeskProtocol with null signal.

    Per spec §12.1 stub discipline:
      - valid boundary contract (passes hot-swap gate)
      - null signal (fails skill gate by construction)
      - directional_claim.sign = "none"
      - staleness = True
      - wide uncertainty
    """

    # Subclasses must override:
    name: str = "stub_base"
    spec_path: str = "desks/base.py"
    target_variable: str = WTI_FRONT_MONTH_CLOSE
    event_id: str = "eia_wpsr"
    horizon_days: int = 7

    @property
    def emit_target_variables(self) -> list[str]:
        return [self.target_variable]

    @property
    def emit_horizons(self) -> list[Horizon]:
        return [EventHorizon(event_id=self.event_id, expected_ts_utc=datetime.now().astimezone())]

    def _provenance(self) -> Provenance:
        return Provenance(
            desk_name=self.name,
            model_name="stub",
            model_version="0.0.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def _build_stub_forecast(self, now_utc: datetime) -> Forecast:
        return Forecast(
            forecast_id=str(uuid.uuid4()),
            emission_ts_utc=now_utc,
            target_variable=self.target_variable,
            horizon=EventHorizon(
                event_id=self.event_id,
                expected_ts_utc=now_utc + timedelta(days=self.horizon_days),
            ),
            point_estimate=0.0,
            uncertainty=UncertaintyInterval(level=0.8, lower=-1e9, upper=1e9),
            directional_claim=DirectionalClaim(variable=self.target_variable, sign="none"),
            staleness=True,
            confidence=0.5,
            provenance=self._provenance(),
        )

    def on_schedule_fire(self, now_utc: datetime) -> list[Forecast]:
        return [self._build_stub_forecast(now_utc)]

    def on_trigger(self, event: ResearchLoopEvent) -> list[Forecast] | None:
        # Stubs don't react to triggers.
        return None


class StubClassifier:
    """Minimal stub conforming to ClassifierProtocol.

    Always emits the same opaque regime ("regime_boot") with P=1.0; no
    transitions. Designed to exercise §14.8 cold-start path.
    """

    name: str = "regime_classifier"
    spec_path: str = "desks/regime_classifier/spec.md"

    def _provenance(self) -> Provenance:
        return Provenance(
            desk_name=self.name,
            model_name="stub_classifier",
            model_version="0.0.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def on_schedule_fire(
        self, now_utc: datetime, recent_forecasts: list[Forecast]
    ) -> list[RegimeLabel]:
        _ = recent_forecasts  # ignored by stub
        return [
            RegimeLabel(
                classification_ts_utc=now_utc,
                regime_id="regime_boot",
                regime_probabilities={"regime_boot": 1.0},
                transition_probabilities={"regime_boot": 1.0},
                classifier_provenance=self._provenance(),
            )
        ]


# Re-exports
_ = Print  # kept available for downstream desk code
_ = Path
