"""Bus validation tests: registry enforcement, dirty-tree rejection."""

from __future__ import annotations

import pytest

from bus import BusValidationError


def test_bus_rejects_dirty_commit_in_production(bus_prod, stub_forecast_factory):
    f = stub_forecast_factory(code_commit="abc-dirty")
    with pytest.raises(BusValidationError) as exc:
        bus_prod.publish_forecast(f)
    assert exc.value.reason == "dirty_tree_rejected"


def test_bus_accepts_dirty_commit_in_development(bus_dev, stub_forecast_factory):
    f = stub_forecast_factory(code_commit="abc-dirty")
    bus_dev.publish_forecast(f)
    # Row persisted (no exception).


def test_bus_dispatches_to_subscribers(bus_dev, stub_forecast_factory):
    from contracts.v1 import Forecast

    received: list[object] = []
    bus_dev.subscribe(Forecast, lambda e: received.append(e))
    f = stub_forecast_factory()
    bus_dev.publish_forecast(f)
    assert len(received) == 1 and received[0].forecast_id == f.forecast_id
