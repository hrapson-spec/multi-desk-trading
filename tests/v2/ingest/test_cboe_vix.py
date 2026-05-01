"""Tests for CboeVIXIngester (Phase B2b Wave 1, agent A1.2).

The Cboe direct path is rights_status='display_only' and
model_eligible=False; the canonical model-eligible VIX is FRED VIXCLS.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.cboe_vix import (
    CBOE_VIX_HISTORY_URL,
    CboeVIXIngester,
    CboeVIXIntradayRejectedError,
    CboeVIXNotPrimary,
)
from v2.ingest.public_data_registry import load_registry
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

VIX_CSV = """DATE,OPEN,HIGH,LOW,CLOSE
2026-04-21,13.20,13.50,13.05,13.40
2026-04-22,13.40,13.85,13.10,13.65
2026-04-23,13.65,14.00,13.55,13.80
"""

VIX_CSV_INTRADAY = """DATE,OPEN,HIGH,LOW,CLOSE
2026-04-21 09:30:00,13.20,13.50,13.05,13.40
"""


class _Counter:
    def __init__(self) -> None:
        self.calls = 0


def _make_http(handler: Callable[[httpx.Request], httpx.Response]) -> HTTPClient:
    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    return client


@pytest.fixture
def writer_and_manifest(tmp_path: Path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    try:
        yield w, m
    finally:
        m.close()


def test_default_warns_and_makes_no_http_call(writer_and_manifest):
    w, m = writer_and_manifest
    counter = _Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        counter.calls += 1
        return httpx.Response(200, text="should-not-be-called")

    http = _make_http(handler)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ing = CboeVIXIngester(w, m, http=http)
    types = [w_.category for w_ in caught]
    assert CboeVIXNotPrimary in types

    # Default fetch returns empty and never touches HTTP.
    out = ing.fetch()
    assert out == []
    assert counter.calls == 0


def test_force_direct_returns_one_fetch_result(writer_and_manifest):
    w, m = writer_and_manifest
    counter = _Counter()

    def handler(request: httpx.Request) -> httpx.Response:
        counter.calls += 1
        assert str(request.url) == CBOE_VIX_HISTORY_URL
        return httpx.Response(
            200,
            content=VIX_CSV.encode("utf-8"),
            headers={
                "Content-Type": "text/csv",
                "Last-Modified": "Wed, 23 Apr 2026 18:00:00 GMT",
            },
        )

    http = _make_http(handler)
    ing = CboeVIXIngester(w, m, force_direct=True, http=http)
    out = ing.fetch()
    assert counter.calls == 1
    assert len(out) == 1
    fr = out[0]
    assert fr.source == "cboe_vix"
    assert fr.series == "VIXCLS_cboe_direct"
    df = fr.data
    assert {"OPEN", "HIGH", "LOW", "CLOSE"}.issubset(df.columns)
    assert "observation_date" in df.columns
    assert len(df) == 3
    assert fr.provenance["method"] == "csv_download"
    assert fr.provenance["scraper_version"] == "v2.b2b.0"


def test_registry_entry_remains_not_model_eligible():
    reg = load_registry()
    cboe = [e for e in reg.entries if e.key == "cboe_vix_direct"]
    assert len(cboe) == 1
    assert cboe[0].model_eligible is False
    assert cboe[0].rights_status == "display_only"


def test_intraday_rows_rejected(writer_and_manifest):
    w, m = writer_and_manifest

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=VIX_CSV_INTRADAY.encode("utf-8"),
            headers={"Last-Modified": "Wed, 23 Apr 2026 18:00:00 GMT"},
        )

    http = _make_http(handler)
    ing = CboeVIXIngester(w, m, force_direct=True, http=http)
    with pytest.raises(CboeVIXIntradayRejectedError):
        ing.fetch()
