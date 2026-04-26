"""CFTCCOTIngester.fetch tests using httpx.MockTransport."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime

import httpx
import pandas as pd
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.cftc_cot import (
    CFTC_CURRENT_YEAR_CSV_URL,
    CFTC_HISTORY_ZIP_URL,
    CFTCCOTIngester,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

# Tuesdays in April 2026: 7, 14, 21, 28. The ingester maps each Tuesday
# to the Friday +3 days at 15:30 ET (= 19:30 UTC during EDT).
TUESDAYS = ["04/07/2026", "04/14/2026", "04/21/2026", "04/28/2026"]
EXPECTED_FRIDAYS_UTC = [
    datetime(2026, 4, 10, 19, 30, tzinfo=UTC),
    datetime(2026, 4, 17, 19, 30, tzinfo=UTC),
    datetime(2026, 4, 24, 19, 30, tzinfo=UTC),
    datetime(2026, 5, 1, 19, 30, tzinfo=UTC),
]


def _row(date_str: str, code: str = "067651", oi: int = 1000) -> dict:
    return {
        "Market_and_Exchange_Names": "CRUDE OIL, LIGHT SWEET - NYMEX",
        "As_of_Date_Form_MM/DD/YYYY": date_str,
        "CFTC_Contract_Market_Code": code,
        "Open_Interest_All": str(oi),
        "Prod_Merc_Positions_Long_All": "100",
        "Prod_Merc_Positions_Short_All": "300",
        "Swap_Positions_Long_All": "75",
        "Swap__Positions_Short_All": "50",
        "M_Money_Positions_Long_All": "500",
        "M_Money_Positions_Short_All": "300",
        "Other_Rept_Positions_Long_All": "125",
        "Other_Rept_Positions_Short_All": "150",
        "NonRept_Positions_Long_All": "45",
        "NonRept_Positions_Short_All": "30",
    }


def _build_zip_bytes(rows: list[dict]) -> bytes:
    df = pd.DataFrame(rows)
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("annualof.txt", csv_bytes)
    return buf.getvalue()


def _build_csv_bytes(rows: list[dict]) -> bytes:
    return pd.DataFrame(rows).to_csv(index=False).encode("utf-8")


def _make_http(handler) -> HTTPClient:
    transport = httpx.MockTransport(handler)
    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(
        transport=transport, follow_redirects=True, timeout=30.0
    )
    return client


def test_fetch_filters_other_market_codes_and_emits_one_result(tmp_path):
    rows = [_row(d) for d in TUESDAYS] + [_row("04/21/2026", code="006742")]
    zip_bytes = _build_zip_bytes(rows)
    expected_url = CFTC_HISTORY_ZIP_URL.format(year=2024)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == expected_url
        return httpx.Response(200, content=zip_bytes)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = CFTCCOTIngester(w, m, years=[2024], http=http)
    # Use as_of in 2025 so 2024 routes to the historical ZIP URL.
    out = ing.fetch(as_of_ts=datetime(2025, 5, 1, tzinfo=UTC))
    assert len(out) == 1
    fr = out[0]
    assert fr.source == "cftc_cot"
    assert fr.series == "067651_disaggregated"
    # Four Tuesdays passed through; the off-code row was filtered.
    assert len(fr.data) == 4
    m.close()
    http.close()


def test_fetch_accepts_quoted_market_code(tmp_path):
    rows = [_row(d, code="'067651'") for d in TUESDAYS]
    csv_bytes = _build_csv_bytes(rows)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == CFTC_CURRENT_YEAR_CSV_URL
        return httpx.Response(200, content=csv_bytes)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = CFTCCOTIngester(w, m, years=[2026], http=http)
    out = ing.fetch(as_of_ts=datetime(2026, 5, 1, tzinfo=UTC))
    assert len(out) == 1
    assert len(out[0].data) == 4
    m.close()
    http.close()


def test_fetch_release_ts_is_friday_three_days_after_tuesday(tmp_path):
    rows = [_row(d) for d in TUESDAYS]
    csv_bytes = _build_csv_bytes(rows)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv_bytes)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = CFTCCOTIngester(w, m, years=[2026], http=http)
    out = ing.fetch(as_of_ts=datetime(2026, 5, 1, tzinfo=UTC))
    fr = out[0]
    # release_ts (the manifest column) is the latest Friday in the batch.
    assert fr.release_ts == EXPECTED_FRIDAYS_UTC[-1]
    # Each row carries its own Friday publication ts.
    rels = sorted(fr.data["release_ts"].tolist())
    expected = sorted(pd.Timestamp(t) for t in EXPECTED_FRIDAYS_UTC)
    assert [pd.Timestamp(r).to_pydatetime() for r in rels] == [
        e.to_pydatetime() for e in expected
    ]
    m.close()
    http.close()


def test_ingest_writes_manifest_row(tmp_path):
    rows = [_row(d) for d in TUESDAYS]
    csv_bytes = _build_csv_bytes(rows)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=csv_bytes)

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = CFTCCOTIngester(w, m, years=[2026], http=http)
    results = ing.ingest(as_of_ts=datetime(2026, 5, 1, tzinfo=UTC))
    assert len(results) == 1
    rows_in_manifest = m.list_all(source="cftc_cot")
    assert len(rows_in_manifest) == 1
    assert rows_in_manifest[0].series == "067651_disaggregated"
    m.close()
    http.close()


def test_fetch_isolates_year_404_failures(tmp_path):
    """A 404 for one year does not break ingestion of other years."""
    good_rows = [_row(d) for d in TUESDAYS]
    good_csv = _build_csv_bytes(good_rows)
    good_zip = _build_zip_bytes(good_rows)

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url == CFTC_HISTORY_ZIP_URL.format(year=2025):
            return httpx.Response(404, content=b"not found")
        if url == CFTC_HISTORY_ZIP_URL.format(year=2023):
            return httpx.Response(200, content=good_zip)
        if url == CFTC_CURRENT_YEAR_CSV_URL:
            return httpx.Response(200, content=good_csv)
        raise AssertionError(f"unexpected URL {url}")

    http = _make_http(handler)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = CFTCCOTIngester(w, m, years=[2023, 2025, 2026], http=http)
    # Run with as_of in 2026: 2023 and 2025 → historical zip; 2026 → current CSV.
    out = ing.fetch(as_of_ts=datetime(2026, 5, 1, tzinfo=UTC))
    assert len(out) == 2  # 2023 and 2026 succeeded, 2025 failed.
    assert ing.last_run_failed_years == [2025]
    m.close()
    http.close()


def test_fetch_with_offline_mode_blocks_network(tmp_path, monkeypatch):
    """Sanity: OfflineModeError fires when the kill switch is set."""
    import v2.ingest._http as _http_mod

    monkeypatch.setattr(_http_mod, "OFFLINE_MODE", True)
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    ing = CFTCCOTIngester(w, m, years=[2024])
    with pytest.raises(_http_mod.OfflineModeError):
        ing.fetch(as_of_ts=datetime(2025, 5, 1, tzinfo=UTC))
    m.close()
