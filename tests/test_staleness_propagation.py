"""Integration test for feed-incident-driven staleness propagation (v1.16 roster).

End-to-end guarantee: when `data_ingestion_failure_handler` v0.2 opens a
`feed_incidents` row, concrete desks whose `feed_names` include the broken
feed emit `Forecast.staleness=True` on their next call. The Controller's
existing `if f.staleness: continue` path (§controller combined_signal) then
excludes them — no extra work needed.

Under the v1.16 roster the test exercises:
- `SupplyDisruptionNewsDesk` (feeds: opec_announcement + eia_wpsr)
- `OilDemandNowcastDesk` (feed: eia_wpsr)
- `StorageCurveDesk` (feeds: eia_wpsr + cftc_cot)

The v1.11/v1.15 macro desk staleness tests are retired — macro is no longer
a standalone alpha desk; its transmission is conditioning-only via
`regime_classifier`, which has no external-feed dependencies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from contracts.v1 import ResearchLoopEvent
from desks.base import StubDesk
from desks.oil_demand_nowcast import ClassicalOilDemandNowcastModel, OilDemandNowcastDesk
from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk
from desks.supply_disruption_news import (
    ClassicalSupplyDisruptionNewsModel,
    SupplyDisruptionNewsDesk,
)
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
# feed_names class attribute is correctly set per v1.16 desk.
# ---------------------------------------------------------------------------


def test_feed_names_declared_per_desk():
    assert "opec_announcement" in SupplyDisruptionNewsDesk.feed_names
    assert "eia_wpsr" in SupplyDisruptionNewsDesk.feed_names
    assert OilDemandNowcastDesk.feed_names == ["eia_wpsr"]
    assert set(StorageCurveDesk.feed_names) == {"eia_wpsr", "cftc_cot"}
    # Base stub declares no dependencies.
    assert StubDesk.feed_names == []


def test_base_stub_with_empty_feed_names_returns_false(conn):
    """Belt-and-braces: the base class helper is safe to call even
    with feed_names=[] and yields False."""
    assert StubDesk()._staleness_from_feeds(conn) is False


# ---------------------------------------------------------------------------
# Helper: OR-gate behaviour across declared feeds.
# ---------------------------------------------------------------------------


def test_storage_curve_goes_stale_when_cftc_cot_breaks(conn):
    _open_incident_via_handler(conn, feed_name="cftc_cot", affected_desks=["storage_curve"])
    assert StorageCurveDesk()._staleness_from_feeds(conn) is True


def test_storage_curve_goes_stale_when_eia_wpsr_breaks(conn):
    _open_incident_via_handler(conn, feed_name="eia_wpsr", affected_desks=["storage_curve"])
    # storage_curve depends on BOTH feeds → either breaking should trigger.
    assert StorageCurveDesk()._staleness_from_feeds(conn) is True


def test_oil_demand_nowcast_unaffected_by_unrelated_feed(conn):
    """`oil_demand_nowcast` only depends on eia_wpsr; a cftc_cot outage
    must NOT set it stale (cross-feed leakage check)."""
    _open_incident_via_handler(conn, feed_name="cftc_cot", affected_desks=["storage_curve"])
    assert OilDemandNowcastDesk()._staleness_from_feeds(conn) is False


# ---------------------------------------------------------------------------
# Forecast emission threads staleness correctly.
# ---------------------------------------------------------------------------


def _trivial_channels():
    """Minimal ObservationChannels stand-in for the desks we touch below."""
    from sim.latent_state import LatentMarket
    from sim.observations import ObservationChannels

    latent = LatentMarket(n_days=300, seed=1).generate()
    return ObservationChannels.build(latent, mode="clean", seed=1)


def test_oil_demand_nowcast_forecast_is_stale_when_eia_wpsr_open(conn):
    channels = _trivial_channels()
    model = ClassicalOilDemandNowcastModel(horizon_days=3)
    model.fit(
        channels.by_desk["demand"].components["demand"],
        channels.by_desk["demand"].components["demand_level"],
        channels.market_price,
    )
    desk = OilDemandNowcastDesk(model=model)

    # No incident → staleness=False.
    f_clean = desk.forecast_from_observation(channels, 220, NOW, conn=conn)
    assert f_clean.staleness is False

    _open_incident_via_handler(
        conn, feed_name="eia_wpsr", affected_desks=["oil_demand_nowcast"]
    )
    f_stale = desk.forecast_from_observation(channels, 220, NOW, conn=conn)
    assert f_stale.staleness is True


def test_oil_demand_nowcast_forecast_backcompat_without_conn(conn):
    """Existing tests call forecast_from_observation without `conn`.
    That path must continue to return staleness=False (no behaviour
    change for pre-v1.7 callers)."""
    channels = _trivial_channels()
    model = ClassicalOilDemandNowcastModel(horizon_days=3)
    model.fit(
        channels.by_desk["demand"].components["demand"],
        channels.by_desk["demand"].components["demand_level"],
        channels.market_price,
    )
    desk = OilDemandNowcastDesk(model=model)

    # Open an incident on eia_wpsr — would set stale if conn were passed.
    _open_incident_via_handler(
        conn, feed_name="eia_wpsr", affected_desks=["oil_demand_nowcast"]
    )
    f = desk.forecast_from_observation(channels, 220, NOW)
    assert f.staleness is False


def test_closing_incident_reverts_staleness(conn):
    channels = _trivial_channels()
    model = ClassicalSupplyDisruptionNewsModel(horizon_days=3)
    geo_obs = channels.by_desk["geopolitics"].components
    model.fit(
        geo_obs["event_indicator"],
        geo_obs["event_intensity"],
        geo_obs["event_intensity_raw"],
        channels.market_price,
    )
    desk = SupplyDisruptionNewsDesk(model=model)

    fid = _open_incident_via_handler(
        conn, feed_name="eia_wpsr", affected_desks=["supply_disruption_news"]
    )
    assert (
        desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is True
    )

    close_feed_incident(
        conn,
        feed_incident_id=fid,
        closed_ts_utc=NOW + timedelta(hours=2),
        resolution_artefact="manual:test",
    )
    assert (
        desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is False
    )


def test_storage_curve_forecast_from_prices_also_honours_staleness(conn):
    """storage_curve has both forecast_from_prices and forecast_from_observation —
    both must thread the conn kwarg."""
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


def test_supply_disruption_news_forecast_honours_opec_staleness(conn):
    """v1.16 merged desk stays stale when its opec_announcement feed breaks —
    mirrors the pre-v1.16 GeopoliticsDesk + SupplyDesk staleness coverage now
    that those two desks are merged."""
    channels = _trivial_channels()
    model = ClassicalSupplyDisruptionNewsModel(horizon_days=3)
    geo_obs = channels.by_desk["geopolitics"].components
    model.fit(
        geo_obs["event_indicator"],
        geo_obs["event_intensity"],
        geo_obs["event_intensity_raw"],
        channels.market_price,
    )
    desk = SupplyDisruptionNewsDesk(model=model)

    # Open unrelated incident first — desk should NOT go stale.
    _open_incident_via_handler(conn, feed_name="cftc_cot", affected_desks=["storage_curve"])
    assert (
        desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is False
    )

    # Now open opec_announcement — desk SHOULD go stale.
    _open_incident_via_handler(
        conn,
        feed_name="opec_announcement",
        affected_desks=["supply_disruption_news"],
    )
    assert (
        desk.forecast_from_observation(channels, 220, NOW, conn=conn).staleness is True
    )


# ---------------------------------------------------------------------------
# Sanity — the registry and the handler agree on open-set.
# ---------------------------------------------------------------------------


def test_handler_and_registry_agree(conn):
    fid = _open_incident_via_handler(
        conn, feed_name="eia_wpsr", affected_desks=["supply_disruption_news"]
    )
    rows = get_open_feed_incidents(conn, "eia_wpsr")
    assert len(rows) == 1
    assert rows[0]["feed_incident_id"] == fid
    assert rows[0]["detected_by"] == "scheduler"
    assert rows[0]["affected_desks"] == ["supply_disruption_news"]
