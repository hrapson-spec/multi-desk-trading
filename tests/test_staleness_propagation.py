"""Integration test for feed-incident-driven staleness propagation.

End-to-end guarantee: when data_ingestion_failure_handler v0.2 opens
a feed_incidents row, concrete desks whose `feed_names` include the
broken feed emit `Forecast.staleness=True` on their next call. The
Controller's existing `if f.staleness: continue` path (§controller
combined_signal) then excludes them — no extra work needed.

The test wires the pieces together without a full scheduler run:
- Open an incident via the handler.
- Call `forecast_from_observation(..., conn=conn)` on each desk.
- Assert staleness=True for desks whose feed_names include the feed.
- Assert staleness=False for desks whose feeds are unaffected.
- Close the incident and verify staleness reverts to False.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from contracts.v1 import ResearchLoopEvent
from desks.base import StubDesk
from desks.demand import DemandDesk
from desks.demand.classical import ClassicalDemandModel
from desks.geopolitics import GeopoliticsDesk
from desks.geopolitics.classical import ClassicalGeopoliticsModel
from desks.macro import MacroDesk
from desks.macro.classical import ClassicalMacroModel
from desks.storage_curve import StorageCurveDesk
from desks.storage_curve.classical import ClassicalStorageCurveModel
from desks.supply import SupplyDesk
from desks.supply.classical import ClassicalSupplyModel
from persistence import (
    close_feed_incident,
    connect,
    get_open_feed_incidents,
    init_db,
)
from research_loop import data_ingestion_failure_handler

NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "staleness.duckdb")
    init_db(c)
    yield c
    c.close()


def _open_incident_via_handler(conn, *, feed_name: str, affected_desks: list[str]) -> str:
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="data_ingestion_failure",
        triggered_at_utc=NOW,
        priority=1,
        payload={
            "feed_name": feed_name,
            "scheduled_release_ts_utc": NOW.isoformat(),
            "affected_desks": affected_desks,
        },
    )
    result = data_ingestion_failure_handler(conn, event)
    import json

    return str(json.loads(result.artefact)["feed_incident_id"])


# ---------------------------------------------------------------------------
# feed_names class attribute is correctly set per-desk
# ---------------------------------------------------------------------------


def test_feed_names_declared_per_desk():
    assert "eia_wpsr" in SupplyDesk.feed_names
    assert "opec_announcement" in SupplyDesk.feed_names
    assert DemandDesk.feed_names == ["eia_wpsr"]
    assert MacroDesk.feed_names == ["fomc_statement"]
    assert "opec_announcement" in GeopoliticsDesk.feed_names
    assert set(StorageCurveDesk.feed_names) == {"eia_wpsr", "cftc_cot"}
    # Base stub declares no dependencies.
    assert StubDesk.feed_names == []


def test_base_stub_with_empty_feed_names_returns_false(conn):
    """Belt-and-braces: the base class helper is safe to call even
    with feed_names=[] and yields False."""
    assert StubDesk()._staleness_from_feeds(conn) is False


# ---------------------------------------------------------------------------
# Helper: OR-gate behaviour across declared feeds
# ---------------------------------------------------------------------------


def test_storage_curve_goes_stale_when_cftc_cot_breaks(conn):
    _open_incident_via_handler(conn, feed_name="cftc_cot", affected_desks=["storage_curve"])
    assert StorageCurveDesk()._staleness_from_feeds(conn) is True


def test_storage_curve_goes_stale_when_eia_wpsr_breaks(conn):
    _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["storage_curve"])
    # storage_curve depends on BOTH feeds → either breaking should trigger.
    assert StorageCurveDesk()._staleness_from_feeds(conn) is True


def test_macro_unaffected_by_cftc_cot(conn):
    """MacroDesk only depends on fomc_statement; a cftc_cot outage
    must NOT set it stale (cross-feed leakage check)."""
    _open_incident_via_handler(conn, feed_name="cftc_cot", affected_desks=["storage_curve"])
    assert MacroDesk()._staleness_from_feeds(conn) is False


# ---------------------------------------------------------------------------
# Forecast emission threads staleness correctly
# ---------------------------------------------------------------------------


def _trivial_channels():
    """Minimal ObservationChannels stand-in for the desks we touch
    below. Built lazily so sim dependencies stay isolated."""
    from sim.latent_state import LatentMarket
    from sim.observations import ObservationChannels

    latent = LatentMarket(n_days=300, seed=1).generate()
    return ObservationChannels.build(latent, mode="clean", seed=1)


def _fit(model, channel_key: str, channels) -> None:
    """Fit a classical desk model against a single channel."""
    if hasattr(model, "fit"):
        target_ret = np.diff(np.log(np.asarray(channels.market_price)))
        # Pad leading zero to keep index alignment with the channel array.
        target_ret = np.concatenate([[0.0], target_ret])
        channel = channels.by_desk[channel_key].components
        if channel_key == "supply":
            model.fit(channel["supply"], target_ret)
        elif channel_key == "demand":
            model.fit(channel["demand"], target_ret)
        elif channel_key == "macro":
            model.fit(channel["xi"], target_ret)


def test_demand_forecast_is_stale_when_eia_wpsr_open(conn):
    channels = _trivial_channels()
    model = ClassicalDemandModel()
    _fit(model, "demand", channels)
    desk = DemandDesk(model=model)

    # No incident → staleness=False.
    f_clean = desk.forecast_from_observation(channels, 220, NOW, conn=conn)
    assert f_clean.staleness is False

    _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["demand"])
    f_stale = desk.forecast_from_observation(channels, 220, NOW, conn=conn)
    assert f_stale.staleness is True


def test_demand_forecast_backcompat_without_conn(conn):
    """Existing tests call forecast_from_observation without `conn`.
    That path must continue to return staleness=False (no behaviour
    change for pre-v1.7 callers)."""
    channels = _trivial_channels()
    model = ClassicalDemandModel()
    _fit(model, "demand", channels)
    desk = DemandDesk(model=model)

    # Open an incident on eia_wpsr — would set stale if conn were passed.
    _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["demand"])
    # But we don't pass conn → staleness stays False.
    f = desk.forecast_from_observation(channels, 220, NOW)
    assert f.staleness is False


def test_closing_incident_reverts_staleness(conn):
    channels = _trivial_channels()
    model = ClassicalSupplyModel()
    _fit(model, "supply", channels)
    desk = SupplyDesk(model=model)

    fid = _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["supply"])
    assert desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is True

    close_feed_incident(
        conn,
        feed_incident_id=fid,
        closed_ts_utc=NOW + timedelta(hours=2),
        resolution_artefact="manual:test",
    )
    assert desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is False


def test_storage_curve_forecast_from_prices_also_honours_staleness(conn):
    """storage_curve has both forecast_from_prices and
    forecast_from_observation — both must thread the conn kwarg."""
    channels = _trivial_channels()
    prices = np.asarray(channels.market_price)
    model = ClassicalStorageCurveModel()
    model.fit(prices)
    desk = StorageCurveDesk(model=model)

    _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["storage_curve"])
    f_prices = desk.forecast_from_prices(prices, 220, NOW, conn=conn)
    f_obs = desk.forecast_from_observation(channels, 220, NOW, conn=conn)
    assert f_prices.staleness is True
    assert f_obs.staleness is True


def test_macro_and_geopolitics_forecasts_honour_staleness(conn):
    channels = _trivial_channels()
    macro_model = ClassicalMacroModel()
    _fit(macro_model, "macro", channels)
    macro_desk = MacroDesk(model=macro_model)

    geo_model = ClassicalGeopoliticsModel()
    # Geopolitics needs event_indicator + intensity — fit on market
    # returns via the model's own .fit, which expects those features.
    target_ret = np.diff(np.log(np.asarray(channels.market_price)))
    target_ret = np.concatenate([[0.0], target_ret])
    geo_obs = channels.by_desk["geopolitics"].components
    geo_model.fit(geo_obs["event_indicator"], geo_obs["event_intensity"], target_ret)
    geo_desk = GeopoliticsDesk(model=geo_model)

    # Open unrelated incident first — neither desk should go stale.
    _open_incident_via_handler(conn, feed_name="cftc_cot", affected_desks=["storage_curve"])
    assert macro_desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is False
    assert geo_desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is False

    # Now open the feed each depends on.
    _open_incident_via_handler(conn, feed_name="fomc_statement", affected_desks=["macro"])
    _open_incident_via_handler(
        conn, feed_name="opec_announcement", affected_desks=["geopolitics", "supply"]
    )
    assert macro_desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is True
    assert geo_desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is True


# ---------------------------------------------------------------------------
# Sanity — the registry and the handler agree on open-set
# ---------------------------------------------------------------------------


def test_handler_and_registry_agree(conn):
    fid = _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["supply"])
    rows = get_open_feed_incidents(conn, "eia_wpsr")
    assert len(rows) == 1
    assert rows[0]["feed_incident_id"] == fid
    assert rows[0]["detected_by"] == "scheduler"
    assert rows[0]["affected_desks"] == ["supply"]
