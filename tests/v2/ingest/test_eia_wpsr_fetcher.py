"""Tests for EIAWPSRIngester (WPSR + petroleum supply EIA series).

Network is mocked via ``httpx.MockTransport`` injected into a real
:class:`v2.ingest._http.HTTPClient` (we replace its internal
``httpx.Client`` so retry/conditional-GET wiring runs as in production).

PIT manifest + writer fixtures follow the pattern in
``tests/v2/pit_store/test_writer.py``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest._secrets import MissingAPIKeyError
from v2.ingest.eia_wpsr import EIAWPSRIngester
from v2.ingest.public_data_registry import (
    PublicDataRegistry,
    RegistryEntry,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

Handler = Callable[[httpx.Request], httpx.Response]


def _eia_payload(
    *,
    value: float | None,
    period: str = "2026-01-09",
    updated: str | None = "2026-01-14T15:30:00-05:00",
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if updated is not None:
        metadata["updated"] = updated
    return {
        "response": {
            "metadata": metadata,
            "data": [
                {
                    "period": period,
                    "value": value,
                    "units": "MBBL",
                    "frequency": "weekly",
                }
            ],
        }
    }


def _make_http_client(handler: Handler) -> HTTPClient:
    """Build an HTTPClient whose internal httpx.Client uses MockTransport."""
    client = HTTPClient()
    # Replace the underlying httpx.Client so MockTransport handles GETs.
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


def _three_series_handler(
    payload_for: dict[str, dict[str, Any]] | None = None,
) -> Handler:
    """Return a handler that serves canned JSON keyed by series ID in URL."""
    payload_for = payload_for or {
        "WCESTUS1": _eia_payload(value=425_000.0),
        "WCSSTUS1": _eia_payload(value=395_000.0),
        "W_EPC0_SAX_YCUOK_MBBL": _eia_payload(value=42_000.0),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        # URL is .../seriesid/{SERIES_ID}
        path = request.url.path
        sid = path.rsplit("/", 1)[-1]
        if sid not in payload_for:
            return httpx.Response(404, content=b"not found")
        return httpx.Response(200, json=payload_for[sid])

    return handler


@pytest.fixture
def writer_and_manifest(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    try:
        yield w, m
    finally:
        m.close()


THREE_SERIES = ["WCESTUS1", "WCSSTUS1", "W_EPC0_SAX_YCUOK_MBBL"]


# ---------------------------------------------------------------------------
# 1. happy path + idempotency + manifest schema_hash stable
# ---------------------------------------------------------------------------


def test_fetch_three_series_writes_three_manifest_rows(writer_and_manifest):
    w, m = writer_and_manifest
    http = _make_http_client(_three_series_handler())

    ing = EIAWPSRIngester(
        w,
        m,
        series_ids=list(THREE_SERIES),
        http=http,
        api_key="dummy",
    )
    results = ing.fetch()
    assert len(results) == 3
    assert {r.series for r in results} == set(THREE_SERIES)
    for r in results:
        assert r.source == "eia"
        assert r.provenance["source"] == "eia"
        assert r.provenance["method"] == "api"
        assert r.provenance["scraper_version"] == "v2.b2b.0"
        assert r.provenance["series_id"] == r.series
        assert r.provenance["endpoint"].endswith(f"/seriesid/{r.series}")
        assert "etag" in r.provenance
        assert "last_modified" in r.provenance
        assert r.revision_ts is None
        assert list(r.data.columns) == [
            "period",
            "value",
            "units",
            "frequency",
            "retrieved_at_utc",
        ]
        assert r.data["value"].dtype.kind == "f"

    # Use the writer directly with the already-fetched results so the
    # retrieved_at_utc field is identical across the two writes; that
    # guarantees byte-identical Parquet → idempotent.
    write_results = []
    for f in results:
        write_results.append(
            w.write_vintage(
                source=f.source,
                series=f.series,
                release_ts=f.release_ts,
                data=f.data,
                provenance=f.provenance,
                revision_ts=f.revision_ts,
            )
        )
    assert len(write_results) == 3
    schema_hashes = {wr.schema_hash for wr in write_results}
    assert len(schema_hashes) == 1  # all three have identical schema

    write_results_2 = []
    for f in results:
        write_results_2.append(
            w.write_vintage(
                source=f.source,
                series=f.series,
                release_ts=f.release_ts,
                data=f.data,
                provenance=f.provenance,
                revision_ts=f.revision_ts,
            )
        )
    assert {wr.manifest_id for wr in write_results_2} == {
        wr.manifest_id for wr in write_results
    }
    assert all(wr.was_revision is False for wr in write_results_2)


# ---------------------------------------------------------------------------
# 2. release_ts parsed from metadata.updated
# ---------------------------------------------------------------------------


def test_release_ts_parsed_from_metadata_updated(writer_and_manifest):
    w, m = writer_and_manifest
    # 15:30 ET == 20:30 UTC (EST winter offset -05:00)
    http = _make_http_client(_three_series_handler())
    ing = EIAWPSRIngester(
        w, m, series_ids=["WCESTUS1"], http=http, api_key="k"
    )
    [r] = ing.fetch()
    assert r.release_ts.year == 2026
    assert r.release_ts.month == 1
    assert r.release_ts.day == 14
    assert r.release_ts.hour == 20
    assert r.release_ts.minute == 30
    assert r.release_ts.utcoffset().total_seconds() == 0
    assert r.provenance["release_ts_confidence"] == "publisher_metadata"


# ---------------------------------------------------------------------------
# 3. null values become NaN
# ---------------------------------------------------------------------------


def test_null_values_become_nan(writer_and_manifest):
    w, m = writer_and_manifest

    payload = {
        "response": {
            "metadata": {"updated": "2026-01-14T15:30:00-05:00"},
            "data": [
                {
                    "period": "2026-01-02",
                    "value": 425_000.0,
                    "units": "MBBL",
                    "frequency": "weekly",
                },
                {
                    "period": "2026-01-09",
                    "value": None,
                    "units": "MBBL",
                    "frequency": "weekly",
                },
                {
                    "period": "2026-01-16",
                    "value": "",
                    "units": "MBBL",
                    "frequency": "weekly",
                },
            ],
        }
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    http = _make_http_client(handler)
    ing = EIAWPSRIngester(
        w, m, series_ids=["WCESTUS1"], http=http, api_key="k"
    )
    [r] = ing.fetch()
    vals = r.data["value"].tolist()
    assert vals[0] == 425_000.0
    assert math.isnan(vals[1])
    assert math.isnan(vals[2])
    # Type is float, not object/string.
    assert r.data["value"].dtype.kind == "f"


# ---------------------------------------------------------------------------
# 4. revision detection
# ---------------------------------------------------------------------------


def test_revision_detected_on_value_change(writer_and_manifest):
    w, m = writer_and_manifest

    state = {"value": 425_000.0}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_eia_payload(value=state["value"]))

    http = _make_http_client(handler)
    ing = EIAWPSRIngester(
        w, m, series_ids=["WCESTUS1"], http=http, api_key="k"
    )
    [first] = ing.ingest()
    assert first.was_revision is False

    state["value"] = 427_500.0
    http2 = _make_http_client(handler)
    ing2 = EIAWPSRIngester(
        w, m, series_ids=["WCESTUS1"], http=http2, api_key="k"
    )
    [second] = ing2.ingest()
    assert second.was_revision is True
    assert second.superseded_manifest_id == first.manifest_id

    rows = m.list_all("eia")
    rev_ts = [r.revision_ts for r in rows if r.manifest_id == second.manifest_id]
    assert rev_ts and rev_ts[0] is not None


# ---------------------------------------------------------------------------
# 5. failure isolation
# ---------------------------------------------------------------------------


def test_404_on_one_series_does_not_abort_batch(writer_and_manifest):
    w, m = writer_and_manifest

    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.path.rsplit("/", 1)[-1]
        if sid == "WCSSTUS1":
            return httpx.Response(404, content=b"not found")
        return httpx.Response(200, json=_eia_payload(value=100.0))

    http = _make_http_client(handler)
    ing = EIAWPSRIngester(
        w, m, series_ids=list(THREE_SERIES), http=http, api_key="k"
    )
    results = ing.fetch()
    assert len(results) == 2
    assert {r.series for r in results} == {"WCESTUS1", "W_EPC0_SAX_YCUOK_MBBL"}
    assert len(ing.last_run_failed_series) == 1
    failed_id, reason = ing.last_run_failed_series[0]
    assert failed_id == "WCSSTUS1"
    assert "404" in reason


# ---------------------------------------------------------------------------
# 6. series IDs derived from registry
# ---------------------------------------------------------------------------


def test_series_ids_default_from_registry(writer_and_manifest):
    w, m = writer_and_manifest

    # Build a tiny synthetic registry with two EIA entries (one ineligible).
    fake_registry = PublicDataRegistry(
        entries=[
            RegistryEntry(
                key="eia_wcestus1",
                source="eia",
                series_id="WCESTUS1",
                description="crude stocks",
                source_url="https://www.eia.gov/x",
                retrieval_method="api",
                rights_status="public",
                model_eligible=True,
                frequency="weekly",
            ),
            RegistryEntry(
                key="eia_other",
                source="eia",
                series_id="OTHER",
                description="other",
                source_url="https://www.eia.gov/y",
                retrieval_method="api",
                rights_status="public",
                model_eligible=True,
                frequency="weekly",
            ),
            # An entry from a different source — must be ignored.
            RegistryEntry(
                key="fred_x",
                source="fred",
                series_id="DCOILWTICO",
                description="wti",
                source_url="https://fred.stlouisfed.org/x",
                retrieval_method="api",
                rights_status="public",
                model_eligible=True,
                frequency="daily",
            ),
        ]
    )

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.path.rsplit("/", 1)[-1]
        seen.append(sid)
        return httpx.Response(200, json=_eia_payload(value=1.0))

    http = _make_http_client(handler)
    ing = EIAWPSRIngester(
        w, m, http=http, api_key="k", registry=fake_registry
    )
    ing.fetch()
    assert seen == ["WCESTUS1", "OTHER"]


def test_default_registry_path_iterates_eia_eligible(writer_and_manifest):
    """Smoke-test the no-arg path against the real registry on disk."""
    w, m = writer_and_manifest

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sid = request.url.path.rsplit("/", 1)[-1]
        seen.append(sid)
        return httpx.Response(200, json=_eia_payload(value=1.0))

    http = _make_http_client(handler)
    ing = EIAWPSRIngester(w, m, http=http, api_key="k")
    ing.fetch()
    # Real registry currently lists 12 EIA model-eligible series; assert
    # the WPSR core is included and the count is positive.
    assert len(seen) >= 3
    assert "WCESTUS1" in seen
    assert "WCSSTUS1" in seen
    assert "W_EPC0_SAX_YCUOK_MBBL" in seen


# ---------------------------------------------------------------------------
# 7. missing API key
# ---------------------------------------------------------------------------


def test_missing_api_key_raises(tmp_path, writer_and_manifest, monkeypatch):
    w, m = writer_and_manifest
    # Point the operator-config loader at an empty file so no eia_api_key.
    cfg = tmp_path / "operator.yaml"
    cfg.write_text("# empty\n", encoding="utf-8")
    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(cfg))
    http = _make_http_client(_three_series_handler())
    # Constructor must succeed without an API key (deferred resolution).
    ing = EIAWPSRIngester(w, m, series_ids=["WCESTUS1"], http=http)
    # ...but fetch() must raise when the key is needed and absent.
    with pytest.raises(MissingAPIKeyError):
        ing.fetch()
