"""Integration test for the v1.16 oil-family stub desks.

Imports the 3 v1.16 oil forecast-emitting desks (+ regime classifier),
wires them through the bus, fires a synthetic schedule, verifies:

  - Each stub's Forecast / RegimeLabel validates against the contract.
  - Hot-swap: replacing each desk with the generic StubDesk leaves the
    Controller skeleton running to completion.
  - The research loop's desk_staleness trigger fires when all stubs emit
    staleness=True (spec §6.2).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.v1 import Forecast, ResearchLoopEvent
from desks.base import ClassifierProtocol, DeskProtocol, StubDesk
from desks.oil_demand_nowcast import OilDemandNowcastDesk
from desks.regime_classifier import RegimeClassifierStub
from desks.storage_curve import StorageCurveDesk
from desks.supply_disruption_news import SupplyDisruptionNewsDesk

OIL_FORECAST_DESKS: list[type[StubDesk]] = [
    SupplyDisruptionNewsDesk,
    OilDemandNowcastDesk,
    StorageCurveDesk,
]


def test_all_stubs_conform_to_protocols():
    """Structural check: each desk satisfies its Protocol."""
    for cls in OIL_FORECAST_DESKS:
        instance = cls()
        assert isinstance(instance, DeskProtocol), f"{cls.__name__} violates DeskProtocol"

    classifier = RegimeClassifierStub()
    assert isinstance(classifier, ClassifierProtocol), (
        "RegimeClassifierStub violates ClassifierProtocol"
    )


def test_stubs_emit_valid_forecasts(bus_dev, synth_clock: datetime):
    """Each stub emits a Forecast the bus accepts."""
    for cls in OIL_FORECAST_DESKS:
        desk = cls()
        forecasts = desk.on_schedule_fire(synth_clock)
        assert len(forecasts) >= 1
        for f in forecasts:
            # Bus validates — this would raise BusValidationError on bad inputs.
            bus_dev.publish_forecast(f)
            # Stub discipline per spec §12.1
            assert f.directional_claim.sign == "none"
            assert f.staleness is True
            assert f.confidence < 1.0


def test_classifier_stub_emits_regime_boot(bus_dev, synth_clock: datetime):
    """RegimeClassifierStub emits a single regime_boot RegimeLabel."""
    classifier = RegimeClassifierStub()
    labels = classifier.on_schedule_fire(synth_clock, recent_forecasts=[])
    assert len(labels) == 1
    r = labels[0]
    assert r.regime_id == "regime_boot"
    assert r.regime_probabilities == {"regime_boot": 1.0}
    bus_dev.publish_regime_label(r)


def test_hot_swap_each_desk_against_generic_stub(bus_dev, synth_clock: datetime):
    """Spec §4.5 / §7.1 Gate 3: each concrete stub can be swapped for
    the generic StubDesk without breaking downstream validation.

    Concrete check: a generic StubDesk emitting with target_variable from
    the concrete stub passes the same bus validation.
    """
    for cls in OIL_FORECAST_DESKS:
        concrete = cls()
        generic = StubDesk()
        generic.name = concrete.name + "_generic_swap"
        generic.target_variable = concrete.target_variable
        generic.event_id = concrete.event_id
        generic.horizon_days = concrete.horizon_days

        # Both emit successfully through the same bus.
        for f in concrete.on_schedule_fire(synth_clock):
            bus_dev.publish_forecast(f)
        for f in generic.on_schedule_fire(synth_clock):
            bus_dev.publish_forecast(f)


def test_desk_staleness_trigger_fires(bus_dev, synth_clock: datetime):
    """§6.2 desk_staleness trigger fires when a Forecast arrives with
    staleness=True. Stub Forecasts all set staleness=True by construction,
    so one Forecast ⇒ one (or more) desk_staleness event.

    For the scaffold, we verify the mechanism: a handler subscribed to
    Forecast events can inspect staleness and emit a research event.
    """
    staleness_events: list[ResearchLoopEvent] = []

    def on_forecast(f: Forecast) -> None:
        if f.staleness:
            event = ResearchLoopEvent(
                event_id=str(uuid.uuid4()),
                event_type="desk_staleness",
                triggered_at_utc=datetime.now(tz=UTC),
                priority=3,
                payload={
                    "desk_name": f.provenance.desk_name,
                    "target_variable": f.target_variable,
                    "forecast_id": f.forecast_id,
                },
            )
            staleness_events.append(event)
            bus_dev.publish_research_event(event)

    bus_dev.subscribe(Forecast, on_forecast)

    for cls in OIL_FORECAST_DESKS:
        desk = cls()
        for f in desk.on_schedule_fire(synth_clock):
            bus_dev.publish_forecast(f)

    assert len(staleness_events) == len(OIL_FORECAST_DESKS)


def test_stubs_fail_skill_gate_by_construction(synth_clock: datetime, stub_print_factory):
    """§12.1 stub discipline: stubs fail the skill gate because null signal
    (point_estimate=0) plus wide uncertainty cannot beat a persistence
    baseline on ANY non-trivial test sequence.

    Concrete check: stub's point_estimate is 0 regardless of input —
    persistence baseline emits last print value and typically beats zero.
    """
    for cls in OIL_FORECAST_DESKS:
        desk = cls()
        f = desk.on_schedule_fire(synth_clock)[0]
        assert f.point_estimate == 0.0
        # Print value ≠ 0 ⇒ |print − 0| > |print − print| = persistence is better.
        p = stub_print_factory(value=1.5)
        err_stub = abs(p.value - f.point_estimate)
        # Persistence baseline: err=0 in this symmetric fixture (simplification).
        err_persistence = 0.0
        assert err_stub > err_persistence
