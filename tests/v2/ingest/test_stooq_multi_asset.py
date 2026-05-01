"""Tests for StooqMultiAssetIngester (Tier 3.B)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.stooq_multi_asset import (
    ASSET_REGISTRY,
    StooqMultiAssetIngester,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

BRENT_FIXTURE = b"""Date,Open,High,Low,Close,Volume
2026-04-22,87.10,87.50,86.80,87.00,90000
2026-04-23,87.00,87.20,86.50,86.70,95000
2026-04-24,86.70,87.40,86.40,87.10,80000
2026-04-25,87.10,87.50,86.90,87.30,85000
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


def test_asset_registry_has_three_assets():
    assert set(ASSET_REGISTRY) == {"brent", "rbob", "ng"}


def test_asset_specs_have_distinct_pit_namespaces():
    sources = {spec.pit_source for spec in ASSET_REGISTRY.values()}
    assert len(sources) == 3
    series = {spec.pit_series for spec in ASSET_REGISTRY.values()}
    assert len(series) == 3


def test_unknown_asset_raises(writer_and_manifest):
    w, m, _ = writer_and_manifest
    with pytest.raises(ValueError, match="unknown asset"):
        StooqMultiAssetIngester(w, m, asset="unobtainium")


def test_brent_ingest_writes_under_brent_namespace(writer_and_manifest):
    w, m, _ = writer_and_manifest

    captured_url = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url.append(str(request.url))
        return httpx.Response(
            200,
            content=BRENT_FIXTURE,
            headers={"Last-Modified": "Fri, 25 Apr 2026 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = StooqMultiAssetIngester(w, m, asset="brent", http=http)
    results = ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))

    assert len(results) == 1
    fr = results[0]
    assert fr.source == "brent_front_eod_pit"
    assert fr.dataset == "front_month_eod_pit_spine"
    assert fr.series == "BRENT_FRONT_DAILY_EOD"
    assert "b.f" in captured_url[0]
    assert fr.provenance["target_variable"] == "brent_front_5d_log_return"
    assert "real_capital_execution" in fr.provenance["spine_forbidden_uses"]


def test_rbob_uses_rb_f_symbol(writer_and_manifest):
    w, m, _ = writer_and_manifest
    captured_url = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url.append(str(request.url))
        return httpx.Response(
            200,
            content=BRENT_FIXTURE,  # any valid OHLCV CSV
            headers={"Last-Modified": "Fri, 25 Apr 2026 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = StooqMultiAssetIngester(w, m, asset="rbob", http=http)
    ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))
    assert "rb.f" in captured_url[0]


def test_ng_uses_ng_f_symbol(writer_and_manifest):
    w, m, _ = writer_and_manifest
    captured_url = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url.append(str(request.url))
        return httpx.Response(
            200,
            content=BRENT_FIXTURE,
            headers={"Last-Modified": "Fri, 25 Apr 2026 21:00:00 GMT"},
        )

    http = _build_http_client(handler)
    ing = StooqMultiAssetIngester(w, m, asset="ng", http=http)
    ing.fetch(as_of_ts=datetime(2026, 4, 28, tzinfo=UTC))
    assert "ng.f" in captured_url[0]


def test_target_variables_match_known_targets():
    """Each asset's target_variable must be in the contracts registry."""
    from contracts.target_variables import KNOWN_TARGETS

    for asset_name, spec in ASSET_REGISTRY.items():
        assert spec.target_variable in KNOWN_TARGETS, (
            f"{asset_name} target_variable {spec.target_variable!r} not in "
            "contracts/target_variables.py KNOWN_TARGETS"
        )
