"""Tests for BakerHughesIngester (Phase B2b Wave 1, agent A4.1).

All HTTP traffic is mocked via httpx.MockTransport. XLSX inputs are
built in-memory via openpyxl.Workbook.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from openpyxl import Workbook

from v2.ingest._http import HTTPClient
from v2.ingest.baker_hughes_rig_count import (
    SERIES_ORDER,
    BakerHughesIngester,
    BakerHughesURLNotConfiguredError,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

NY = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_xlsx_bytes() -> bytes:
    """Build a 6-row weekly BH-pivot-table-shaped XLSX in memory.

    Header uses the "us_oil_total" direct path for simplicity.
    """
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "Date",
            "US Oil Total",
            "US Gas Total",
            "US Total",
            "Canada Total",
            "NA Total",
        ]
    )
    # 6 weekly Fridays.
    fridays = [
        date(2026, 3, 13),
        date(2026, 3, 20),
        date(2026, 3, 27),
        date(2026, 4, 3),
        date(2026, 4, 10),
        date(2026, 4, 17),
    ]
    for i, d in enumerate(fridays):
        oil = 500 + i
        gas = 100 + i
        us_total = oil + gas
        canada = 200 + i
        na = us_total + canada
        ws.append([d, oil, gas, us_total, canada, na])

    bio = io.BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _xlsx_path(tmp_path: Path) -> Path:
    p = tmp_path / "rigcount.xlsx"
    p.write_bytes(_build_xlsx_bytes())
    return p


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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manual_xlsx_path_yields_five_series(writer_and_manifest, tmp_path):
    w, m, _ = writer_and_manifest
    p = _xlsx_path(tmp_path)
    ing = BakerHughesIngester(w, m, manual_xlsx_path=p)
    results = ing.fetch()
    assert len(results) == 5
    assert {r.series for r in results} == set(SERIES_ORDER)
    for fr in results:
        assert fr.source == "baker_hughes_rig_count"
        assert list(fr.data.columns) == [
            "observation_date",
            "value",
            "units",
            "retrieved_at_utc",
        ]
        assert fr.provenance["method"] == "manual_xlsx"
        assert len(fr.data) == 6


def test_url_path_via_mock_transport(writer_and_manifest, tmp_path):
    w, m, _ = writer_and_manifest
    payload = _build_xlsx_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert "rigcount.bakerhughes.com" in str(request.url)
        return httpx.Response(
            200,
            content=payload,
            headers={
                "Content-Type": (
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                )
            },
        )

    http = _build_http_client(handler)
    ing = BakerHughesIngester(
        w,
        m,
        http=http,
        archive_url="https://rigcount.bakerhughes.com/static-files/abc-xyz",
    )
    results = ing.fetch()
    assert len(results) == 5
    assert {r.series for r in results} == set(SERIES_ORDER)
    for fr in results:
        assert fr.provenance["method"] == "xlsx_download"
        assert (
            fr.provenance["endpoint"]
            == "https://rigcount.bakerhughes.com/static-files/abc-xyz"
        )


def test_both_none_raises_typed_error(writer_and_manifest):
    w, m, _ = writer_and_manifest
    with pytest.raises(BakerHughesURLNotConfiguredError) as exc:
        BakerHughesIngester(w, m)
    assert "operator_runbook_public_data.md" in str(exc.value)


def test_release_ts_is_friday_1300_eastern_in_utc(writer_and_manifest, tmp_path):
    w, m, _ = writer_and_manifest
    p = _xlsx_path(tmp_path)
    ing = BakerHughesIngester(w, m, manual_xlsx_path=p)
    results = ing.fetch()
    # Latest weekly row in fixture = 2026-04-17.
    expected_local = datetime.combine(
        date(2026, 4, 17), time(13, 0), tzinfo=NY
    )
    expected_utc = expected_local.astimezone(UTC)
    for fr in results:
        assert fr.release_ts == expected_utc


def test_ingest_writes_five_manifest_rows(writer_and_manifest, tmp_path):
    w, m, _ = writer_and_manifest
    p = _xlsx_path(tmp_path)
    ing = BakerHughesIngester(w, m, manual_xlsx_path=p)
    written = ing.ingest()
    assert len(written) == 5
    rows = m.list_all(source="baker_hughes_rig_count")
    assert len(rows) == 5
    assert {r.series for r in rows} == set(SERIES_ORDER)
