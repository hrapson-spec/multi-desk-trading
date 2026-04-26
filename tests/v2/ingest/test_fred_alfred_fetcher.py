"""Tests for FREDAlfredIngester (Phase B2b Wave 1, agent A1.1).

All HTTP traffic is mocked via httpx.MockTransport — never touch the
network. Construct a fresh HTTPClient and swap its underlying httpx.Client
for one wired to MockTransport.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest._secrets import MissingAPIKeyError
from v2.ingest.fred_alfred import FREDAlfredIngester
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _series_payload(series_id: str, last_updated: str = "2026-04-23 09:08:01-05") -> dict:
    return {
        "seriess": [
            {
                "id": series_id,
                "last_updated": last_updated,
                "units": "USD per Barrel",
                "frequency": "Daily",
                "frequency_short": "D",
            }
        ]
    }


def _observations_payload(rows: list[tuple[str, str]]) -> dict:
    return {
        "observations": [
            {
                "realtime_start": "2026-04-23",
                "realtime_end": "2026-04-23",
                "date": d,
                "value": v,
            }
            for d, v in rows
        ]
    }


def _build_http_client(handler: Callable[[httpx.Request], httpx.Response]) -> HTTPClient:
    """Create an HTTPClient whose internal client is wired to MockTransport."""
    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler), timeout=5.0)
    return client


def _route_handler(routes: dict[str, dict]) -> Callable[[httpx.Request], httpx.Response]:
    """Return a handler that dispatches by (path, series_id) -> JSON dict.

    Keys are ``"<endpoint_suffix>:<series_id>[:<rt_start>:<rt_end>]"`` strings,
    e.g. ``"/series:DCOILWTICO"`` or ``"/series/observations:VIXCLS:2026-01-01:2026-01-31"``.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        suffix = request.url.path.removeprefix("/fred")
        sid = request.url.params.get("series_id", "")
        rt_start = request.url.params.get("realtime_start")
        rt_end = request.url.params.get("realtime_end")
        key = (
            f"{suffix}:{sid}:{rt_start}:{rt_end}"
            if rt_start and rt_end
            else f"{suffix}:{sid}"
        )
        body = routes.get(key)
        if body is None:
            # Fall back to no-rt key.
            body = routes.get(f"{suffix}:{sid}")
        if body is None:
            return httpx.Response(404, json={"error": f"no route for {key!r}"})
        return httpx.Response(
            200,
            content=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    return handler


@pytest.fixture
def writer_and_manifest(tmp_path: Path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    try:
        yield w, m, tmp_path
    finally:
        m.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_happy_path_two_series(writer_and_manifest):
    w, m, _ = writer_and_manifest
    routes: dict[str, dict] = {
        "/series:DCOILWTICO": _series_payload("DCOILWTICO"),
        "/series:VIXCLS": _series_payload("VIXCLS", last_updated="2026-04-23 16:00:00-04"),
        "/series/observations:DCOILWTICO": _observations_payload(
            [("2026-04-21", "82.5"), ("2026-04-22", "83.1")]
        ),
        "/series/observations:VIXCLS": _observations_payload(
            [("2026-04-21", "13.2"), ("2026-04-22", "13.4")]
        ),
    }
    http = _build_http_client(_route_handler(routes))
    ing = FREDAlfredIngester(
        w,
        m,
        series_ids=["DCOILWTICO", "VIXCLS"],
        http=http,
        api_key="test_key_xyz",
    )
    results = ing.ingest()
    assert len(results) == 2
    assert all(r.was_revision is False for r in results)

    # Schema-hash deterministic across the two writes (same dtypes).
    assert results[0].schema_hash == results[1].schema_hash

    # Idempotent re-ingest returns identical manifest_ids.
    results2 = ing.ingest()
    for r1, r2 in zip(results, results2, strict=True):
        assert r1.manifest_id == r2.manifest_id
        assert r1.checksum == r2.checksum

    # Manifest rows look right.
    rows = m.list_all("fred")
    assert len(rows) == 2
    by_series = {r.series: r for r in rows}
    assert set(by_series) == {"DCOILWTICO", "VIXCLS"}
    for sid, row in by_series.items():
        assert row.provenance["series_id"] == sid
        assert row.provenance["scraper_version"] == "v2.b2b.0"
        assert row.provenance["method"] == "api"
        assert row.revision_ts is None


def test_revision_detection_on_value_change(writer_and_manifest):
    w, m, _ = writer_and_manifest
    routes_v1: dict[str, dict] = {
        "/series:DCOILWTICO": _series_payload("DCOILWTICO"),
        "/series/observations:DCOILWTICO": _observations_payload(
            [("2026-04-21", "82.5"), ("2026-04-22", "83.1")]
        ),
    }
    http1 = _build_http_client(_route_handler(routes_v1))
    ing1 = FREDAlfredIngester(
        w, m, series_ids=["DCOILWTICO"], http=http1, api_key="test_key"
    )
    r1 = ing1.ingest()
    assert r1[0].was_revision is False

    routes_v2 = dict(routes_v1)
    routes_v2["/series/observations:DCOILWTICO"] = _observations_payload(
        [("2026-04-21", "82.5"), ("2026-04-22", "83.7")]  # last value revised
    )
    http2 = _build_http_client(_route_handler(routes_v2))
    ing2 = FREDAlfredIngester(
        w, m, series_ids=["DCOILWTICO"], http=http2, api_key="test_key"
    )
    r2 = ing2.ingest()
    assert r2[0].was_revision is True
    assert r2[0].superseded_manifest_id == r1[0].manifest_id

    older = m.get(r1[0].manifest_id)
    newer = m.get(r2[0].manifest_id)
    assert older is not None and newer is not None
    assert older.superseded_by == r2[0].manifest_id
    assert newer.revision_ts is not None


def test_vintage_replay_lives_independently(writer_and_manifest):
    w, m, _ = writer_and_manifest
    # Current vintage and a back-vintage with different values for the same date.
    routes: dict[str, dict] = {
        "/series:DCOILWTICO": _series_payload(
            "DCOILWTICO", last_updated="2026-04-23 09:08:01-05"
        ),
        "/series/observations:DCOILWTICO": _observations_payload(
            [("2026-04-21", "82.5")]
        ),
        "/series/observations:DCOILWTICO:2026-01-01:2026-01-31": _observations_payload(
            [("2026-04-21", "80.1")]
        ),
    }
    http = _build_http_client(_route_handler(routes))

    ing_current = FREDAlfredIngester(
        w, m, series_ids=["DCOILWTICO"], http=http, api_key="test_key"
    )
    r_current = ing_current.ingest()
    assert len(r_current) == 1

    # Replay with explicit realtime range -> different observations response, but
    # same release_ts (last_updated) so writer treats this as a revision and
    # both rows live in the manifest.
    ing_replay = FREDAlfredIngester(
        w,
        m,
        series_ids=["DCOILWTICO"],
        http=http,
        api_key="test_key",
        realtime_start=date(2026, 1, 1),
        realtime_end=date(2026, 1, 31),
    )
    r_replay = ing_replay.ingest()
    assert len(r_replay) == 1
    assert r_replay[0].manifest_id != r_current[0].manifest_id

    rows = m.list_all("fred")
    assert len(rows) == 2

    # Replay row carries the realtime_start/end in provenance.
    by_id = {r.manifest_id: r for r in rows}
    replay_row = by_id[r_replay[0].manifest_id]
    assert replay_row.provenance.get("realtime_start") == "2026-01-01"
    assert replay_row.provenance.get("realtime_end") == "2026-01-31"


def test_missing_value_dot_becomes_nan(writer_and_manifest):
    w, m, _ = writer_and_manifest
    routes: dict[str, dict] = {
        "/series:DCOILWTICO": _series_payload("DCOILWTICO"),
        "/series/observations:DCOILWTICO": _observations_payload(
            [("2026-04-21", "82.5"), ("2026-04-22", "."), ("2026-04-23", "83.1")]
        ),
    }
    http = _build_http_client(_route_handler(routes))
    ing = FREDAlfredIngester(
        w, m, series_ids=["DCOILWTICO"], http=http, api_key="test_key"
    )
    results = ing.fetch()
    assert len(results) == 1
    df = results[0].data
    # column dtype is float, missing value is NaN (not the string ".").
    assert df["value"].dtype.kind == "f"
    vals = df["value"].tolist()
    assert vals[0] == pytest.approx(82.5)
    assert math.isnan(vals[1])
    assert vals[2] == pytest.approx(83.1)
    # Sanity: the date column is a Python date.
    assert isinstance(df["observation_date"].iloc[0], date)


def test_missing_api_key_raises(writer_and_manifest, tmp_path: Path, monkeypatch):
    w, m, _ = writer_and_manifest
    empty = tmp_path / "operator.yaml"
    empty.write_text("other_key: zzz\n")
    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(empty))
    # Constructor must succeed without an API key (deferred resolution).
    ing = FREDAlfredIngester(w, m, series_ids=["DCOILWTICO"])
    # ...but fetch() must raise when the key is needed and absent.
    with pytest.raises(MissingAPIKeyError):
        ing.fetch()


def test_default_series_ids_from_registry(writer_and_manifest):
    """When series_ids=None, ingester pulls model-eligible 'fred' entries from registry."""
    w, m, _ = writer_and_manifest
    # Build a routing handler that responds to ANY series_id with canned data.
    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.params.get("series_id", "X")
        suffix = request.url.path.removeprefix("/fred")
        if suffix == "/series":
            body: dict[str, Any] = _series_payload(sid)
        else:
            body = _observations_payload([("2026-04-21", "1.0")])
        return httpx.Response(
            200, content=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )

    http = _build_http_client(handler)
    ing = FREDAlfredIngester(w, m, http=http, api_key="test_key")
    # Should be > 1 series (the registry lists ~11 model-eligible fred entries).
    assert len(ing._series_ids) >= 2
    res = ing.fetch()
    assert len(res) == len(ing._series_ids)
    assert all(isinstance(r.data, pd.DataFrame) for r in res)
    assert all(isinstance(r.release_ts, datetime) for r in res)
