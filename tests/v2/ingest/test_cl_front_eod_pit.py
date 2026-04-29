"""Tests for CLFrontEODPITIngester (the Tier 1.B PIT spine wrapper)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.cl_front_eod_pit import CLFrontEODPITIngester
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

STOOQ_FIXTURE = b"""Date,Open,High,Low,Close,Volume
2026-04-22,82.10,82.50,81.80,82.00,150000
2026-04-23,82.00,82.20,81.50,81.70,160000
2026-04-24,81.70,82.40,81.40,82.10,140000
2026-04-25,82.10,82.50,81.90,82.30,130000
"""


def _build_http_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> HTTPClient:
    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), timeout=5.0
    )
    return client


@pytest.fixture
def writer_and_manifest(tmp_path: Path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    try:
        yield w, m, tmp_path
    finally:
        m.close()


def test_pit_spine_re_emits_under_dedicated_namespace(writer_and_manifest):
    w, m, _ = writer_and_manifest

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=STOOQ_FIXTURE,
            headers={"Last-Modified": "Fri, 25 Apr 2026 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = CLFrontEODPITIngester(w, m, http=http)
    results = ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))

    assert len(results) == 1
    fr = results[0]
    assert fr.source == "cl_front_eod_pit"
    assert fr.dataset == "front_month_eod_pit_spine"
    assert fr.series == "CL_FRONT_DAILY_EOD"


def test_pit_spine_provenance_includes_license_caveat(writer_and_manifest):
    w, m, _ = writer_and_manifest

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=STOOQ_FIXTURE,
            headers={"Last-Modified": "Fri, 25 Apr 2026 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = CLFrontEODPITIngester(w, m, http=http)
    results = ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))

    fr = results[0]
    assert fr.provenance["method"] == "cl_front_eod_pit_wrapper"
    assert fr.provenance["underlying_source"] == "wti_prices"
    assert "license_note" in fr.provenance
    assert "free_source_rehearsal_only" in fr.provenance["license_note"]
    assert "real_capital_execution" in fr.provenance["spine_forbidden_uses"]


def test_pit_spine_filters_observation_window(writer_and_manifest):
    w, m, _ = writer_and_manifest

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=STOOQ_FIXTURE,
            headers={"Last-Modified": "Fri, 25 Apr 2026 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = CLFrontEODPITIngester(
        w, m, http=http,
        since=date(2026, 4, 23),
        until=date(2026, 4, 24),
    )
    results = ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))

    fr = results[0]
    # 2 rows in the window
    assert len(fr.data) == 2
    assert fr.observation_start == date(2026, 4, 23)
    assert fr.observation_end == date(2026, 4, 24)


def test_pit_spine_vintage_quality_for_old_data(writer_and_manifest):
    """Historical data (>1 day stale) gets release_lag_safe_revision_unknown."""
    w, m, _ = writer_and_manifest

    old_fixture = b"""Date,Open,High,Low,Close,Volume
2024-04-22,82.10,82.50,81.80,82.00,150000
2024-04-23,82.00,82.20,81.50,81.70,160000
"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=old_fixture,
            headers={"Last-Modified": "Tue, 23 Apr 2024 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = CLFrontEODPITIngester(w, m, http=http)
    results = ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))

    fr = results[0]
    assert fr.vintage_quality == "release_lag_safe_revision_unknown"
