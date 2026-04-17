"""Smoke tests for the 4 new classical specialists (plan §A).

Covers fit/predict/fingerprint determinism per model. End-to-end
gate-pass validation lives in tests/test_phase_a_clean_observations.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from desks.demand.classical import ClassicalDemandModel
from desks.geopolitics.classical import ClassicalGeopoliticsModel
from desks.macro.classical import ClassicalMacroModel
from desks.supply.classical import ClassicalSupplyModel
from sim.latent_state import LatentMarket
from sim.observations import ObservationChannels


@pytest.fixture(scope="module")
def channels():
    path = LatentMarket(n_days=300, seed=11).generate()
    return ObservationChannels.build(path, mode="clean", seed=0)


# ---------------------------------------------------------------------------
# Supply
# ---------------------------------------------------------------------------


def test_supply_classical_fits_and_predicts(channels):
    supply = channels.by_desk["supply"].components["supply"]
    mp = channels.market_price
    m = ClassicalSupplyModel()
    m.fit(supply[:200], mp[:200])
    out = m.predict(supply, mp, 220)
    assert out is not None
    point, score = out
    assert np.isfinite(point) and np.isfinite(score)
    assert point > 0


def test_supply_classical_fingerprint_is_deterministic(channels):
    supply = channels.by_desk["supply"].components["supply"]
    mp = channels.market_price
    m = ClassicalSupplyModel()
    assert m.fingerprint() == "unfit"
    m.fit(supply[:200], mp[:200])
    assert m.fingerprint() == m.fingerprint()
    assert m.fingerprint().startswith("sha256:")


def test_supply_classical_unfit_predict_raises(channels):
    supply = channels.by_desk["supply"].components["supply"]
    m = ClassicalSupplyModel()
    with pytest.raises(RuntimeError, match="not fitted"):
        m.predict(supply, channels.market_price, 100)


# ---------------------------------------------------------------------------
# Demand
# ---------------------------------------------------------------------------


def test_demand_classical_fits_and_predicts(channels):
    demand = channels.by_desk["demand"].components["demand"]
    mp = channels.market_price
    m = ClassicalDemandModel()
    m.fit(demand[:200], mp[:200])
    out = m.predict(demand, mp, 220)
    assert out is not None
    point, score = out
    assert np.isfinite(point) and np.isfinite(score)


# ---------------------------------------------------------------------------
# Geopolitics
# ---------------------------------------------------------------------------


def test_geopolitics_classical_fits_and_predicts(channels):
    ind = channels.by_desk["geopolitics"].components["event_indicator"]
    inten = channels.by_desk["geopolitics"].components["event_intensity"]
    mp = channels.market_price
    m = ClassicalGeopoliticsModel()
    m.fit(ind[:200], inten[:200], mp[:200])
    out = m.predict(ind, inten, mp, 220)
    assert out is not None
    point, score = out
    assert np.isfinite(point) and np.isfinite(score)


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------


def test_macro_classical_fits_and_predicts(channels):
    xi = channels.by_desk["macro"].components["xi"]
    mp = channels.market_price
    m = ClassicalMacroModel(lookback=60)
    m.fit(xi[:250], mp[:250])
    out = m.predict(xi, mp, 270)
    assert out is not None
    point, score = out
    assert np.isfinite(point) and np.isfinite(score)


def test_macro_classical_insufficient_history_returns_none(channels):
    xi = channels.by_desk["macro"].components["xi"]
    mp = channels.market_price
    m = ClassicalMacroModel(lookback=60)
    m.fit(xi[:250], mp[:250])
    # i = 10 is before the lookback=60 window; predict returns None
    assert m.predict(xi, mp, 10) is None


# ---------------------------------------------------------------------------
# Desk wiring (stub-compat when model is None; classical emission otherwise)
# ---------------------------------------------------------------------------


def test_desk_stub_mode_still_works(channels):
    """Each desk without a model still emits a valid stub Forecast."""
    from datetime import UTC, datetime

    from desks.demand import DemandDesk
    from desks.geopolitics import GeopoliticsDesk
    from desks.macro import MacroDesk
    from desks.supply import SupplyDesk

    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    for desk_cls in (SupplyDesk, DemandDesk, GeopoliticsDesk, MacroDesk):
        d = desk_cls()  # no model
        f = d._build_stub_forecast(now)
        assert f.staleness is True
        assert f.directional_claim.sign == "none"


def test_desk_classical_mode_emits_valid_forecast(channels):
    from datetime import UTC, datetime

    from desks.supply import ClassicalSupplyModel, SupplyDesk

    supply = channels.by_desk["supply"].components["supply"]
    mp = channels.market_price
    model = ClassicalSupplyModel()
    model.fit(supply[:200], mp[:200])
    desk = SupplyDesk(model=model)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    f = desk.forecast_from_observation(channels, 220, now)
    assert f.staleness is False
    assert f.directional_claim.sign == "positive"
    assert f.confidence == 0.7
    assert f.provenance.model_name == "ridge_supply"
