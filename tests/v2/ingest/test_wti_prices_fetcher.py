"""WTIPricesIngester.fetch tests using httpx.MockTransport."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import httpx
import pandas as pd
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.wti_prices import (
    IntradayPayloadError,
    WTIPricesIngester,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

_AS_OF = datetime(2026, 4, 25, 18, 0, tzinfo=UTC)


def _ohlcv_csv(n_rows: int, end: date | None = None) -> bytes:
    end = end or (date(2026, 4, 25) - timedelta(days=1))
    rows = []
    for i in range(n_rows):
        d = end - timedelta(days=(n_rows - 1 - i))
        rows.append(
            {
                "Date": d.isoformat(),
                "Open": 80.0 + i * 0.1,
                "High": 81.0 + i * 0.1,
                "Low": 79.0 + i * 0.1,
                "Close": 80.5 + i * 0.1,
                "Volume": 100_000 + i,
            }
        )
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def _make_http(handler) -> HTTPClient:
    transport = httpx.MockTransport(handler)
    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(
        transport=transport, follow_redirects=True, timeout=30.0
    )
    return client


def test_stooq_happy_path_30_rows(tmp_path):
    csv = _ohlcv_csv(30)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "stooq.com"
        return httpx.Response(
            200,
            content=csv,
            headers={"Last-Modified": "Fri, 24 Apr 2026 21:00:00 GMT"},
        )

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = WTIPricesIngester(w, m, http=http)
    out = ing.fetch(as_of_ts=_AS_OF)
    assert len(out) == 1
    fr = out[0]
    assert fr.series == "CL_FRONT_DAILY_EOD"
    assert fr.source == "wti_prices"
    assert len(fr.data) == 30
    assert fr.provenance["data_source"] == "stooq"
    assert fr.release_ts == datetime(2026, 4, 24, 21, 0, tzinfo=UTC)
    m.close()
    http.close()


def test_intraday_row_raises(tmp_path):
    rows = [
        {
            "Date": "2026-04-25 14:30:00",
            "Open": 80.0,
            "High": 81.0,
            "Low": 79.0,
            "Close": 80.5,
            "Volume": 100,
        }
    ]
    csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = WTIPricesIngester(w, m, http=http, source_priority=["stooq"])
    with pytest.raises(IntradayPayloadError):
        ing.fetch(as_of_ts=_AS_OF)
    m.close()
    http.close()


def test_future_dated_row_dropped_not_raised(tmp_path):
    """A future-dated row is filtered out, but valid rows still flow through."""
    end = date(2026, 4, 25) - timedelta(days=1)  # yesterday
    rows = []
    for i in range(5):
        d = end - timedelta(days=(4 - i))
        rows.append(
            {
                "Date": d.isoformat(),
                "Open": 80.0,
                "High": 81.0,
                "Low": 79.0,
                "Close": 80.5,
                "Volume": 100,
            }
        )
    # Inject a tomorrow-dated row.
    rows.append(
        {
            "Date": (date(2026, 4, 26)).isoformat(),
            "Open": 80.0,
            "High": 81.0,
            "Low": 79.0,
            "Close": 80.5,
            "Volume": 100,
        }
    )
    csv = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = WTIPricesIngester(w, m, http=http, source_priority=["stooq"])
    out = ing.fetch(as_of_ts=_AS_OF)
    assert len(out) == 1
    # 5 historical rows kept, the tomorrow row dropped.
    assert len(out[0].data) == 5
    m.close()
    http.close()


def test_yahoo_fallback_on_stooq_503(tmp_path):
    yahoo_csv = _ohlcv_csv(30)
    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        call_log.append(host)
        if host == "stooq.com":
            return httpx.Response(503, content=b"")
        if host == "query1.finance.yahoo.com":
            return httpx.Response(200, content=yahoo_csv)
        raise AssertionError(f"unexpected host {host}")

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    # Explicitly include yahoo: Yahoo is no longer in the default source_priority
    # (decommissioned 2026-04-29) but operator subclasses may still list it.
    ing = WTIPricesIngester(w, m, http=http, source_priority=["stooq", "yahoo"])
    out = ing.fetch(as_of_ts=_AS_OF)
    assert len(out) == 1
    fr = out[0]
    assert fr.provenance["data_source"] == "yahoo"
    assert len(fr.data) == 30
    # Stooq was retried 4 times (initial + 3 retries) before falling back.
    stooq_calls = [c for c in call_log if c == "stooq.com"]
    assert len(stooq_calls) == 4
    m.close()
    http.close()


def test_yahoo_429_raises_empty_body_and_falls_through_to_stooq(tmp_path):
    """R2 regression: Yahoo returning 429 (HTML body) must not propagate
    ValueError out of fetch(); it should raise _EmptyBodyError internally
    and fall through to stooq as the next source."""
    stooq_csv = _ohlcv_csv(10)

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "query1.finance.yahoo.com":
            return httpx.Response(429, content=b"Edge: Too Many Requests")
        if host == "stooq.com":
            return httpx.Response(200, content=stooq_csv)
        raise AssertionError(f"unexpected host {host}")

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    # Explicitly use yahoo first so we can observe the fallthrough.
    ing = WTIPricesIngester(w, m, http=http, source_priority=["yahoo", "stooq"])
    out = ing.fetch(as_of_ts=_AS_OF)
    assert len(out) == 1
    fr = out[0]
    # Must have fallen through to stooq.
    assert fr.provenance["data_source"] == "stooq"
    assert len(fr.data) == 10
    m.close()
    http.close()


def test_yahoo_non_csv_body_treated_as_empty_source(tmp_path):
    """R2 regression: Yahoo returning 200 with HTML (malformed CSV) raises
    _EmptyBodyError via the ValueError guard and falls through to stooq."""
    stooq_csv = _ohlcv_csv(5)

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "query1.finance.yahoo.com":
            # 200 but HTML body — columns will be garbage after pd.read_csv.
            return httpx.Response(
                200,
                content=b"<html><body>Unauthorized</body></html>",
                headers={"content-type": "text/html"},
            )
        if host == "stooq.com":
            return httpx.Response(200, content=stooq_csv)
        raise AssertionError(f"unexpected host {host}")

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = WTIPricesIngester(w, m, http=http, source_priority=["yahoo", "stooq"])
    out = ing.fetch(as_of_ts=_AS_OF)
    assert len(out) == 1
    # Stooq must be the effective source.
    assert out[0].provenance["data_source"] == "stooq"
    assert len(out[0].data) == 5
    m.close()
    http.close()


def test_stooq_primary_path_unaffected_by_yahoo_decommission(tmp_path):
    """Regression: default source_priority is now ['stooq'] only; stooq happy
    path must still return a valid FetchResult without touching Yahoo."""
    stooq_csv = _ohlcv_csv(20)
    yahoo_called: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "query1.finance.yahoo.com":
            yahoo_called.append(True)
        return httpx.Response(200, content=stooq_csv)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    # No source_priority override — uses the new default of ["stooq"].
    ing = WTIPricesIngester(w, m, http=http)
    out = ing.fetch(as_of_ts=_AS_OF)
    assert len(out) == 1
    assert out[0].provenance["data_source"] == "stooq"
    assert len(out[0].data) == 20
    # Yahoo must never have been contacted.
    assert yahoo_called == [], "Yahoo should not be contacted when stooq succeeds"
    m.close()
    http.close()


def test_idempotent_reingest_returns_same_manifest_id(tmp_path):
    csv = _ohlcv_csv(30)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=csv,
            headers={"Last-Modified": "Fri, 24 Apr 2026 21:00:00 GMT"},
        )

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = WTIPricesIngester(w, m, http=http, source_priority=["stooq"])
    first = ing.ingest(as_of_ts=_AS_OF)
    second = ing.ingest(as_of_ts=_AS_OF)
    assert first[0].manifest_id == second[0].manifest_id
    m.close()
    http.close()
