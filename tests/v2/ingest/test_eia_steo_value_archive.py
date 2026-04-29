"""Tests for EIASTEOValueArchiveIngester."""

from __future__ import annotations

import io
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.eia_steo_value_archive import (
    ARCHIVE_INDEX_URL,
    EIASTEOValueArchiveIngester,
    STEOArchiveIssue,
    parse_archive_index,
    parse_steo_workbook,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter


def _build_http_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> HTTPClient:
    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        timeout=5.0,
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


def _sample_archive_html() -> bytes:
    return b"""
    <table>
      <tr>
        <td>April 2026</td>
        <td>04/07/2026</td>
        <td><a href="archives/apr26.pdf">apr26.pdf</a></td>
        <td><a href="archives/apr26_base.xlsx">apr26_base.xlsx</a></td>
      </tr>
      <tr>
        <td>June 2013</td>
        <td>06/11/2013</td>
        <td><a href="archives/jun13.pdf">jun13.pdf</a></td>
        <td><a href="archives/jun13_base.xls">jun13_base.xls</a></td>
      </tr>
    </table>
    """


def _sheet_with_series(code: str, label: str, values: list[float]) -> pd.DataFrame:
    frame = pd.DataFrame([[pd.NA for _ in range(6)] for _ in range(8)])
    frame.iloc[0, 1] = "Test table"
    frame.iloc[2, 2] = 2026
    frame.iloc[3, 2] = "Jan"
    frame.iloc[3, 3] = "Feb"
    frame.iloc[3, 4] = "Mar"
    frame.iloc[3, 5] = "Apr"
    frame.iloc[5, 0] = code
    frame.iloc[5, 1] = label
    for i, value in enumerate(values, start=2):
        frame.iloc[5, i] = value
    return frame


def _sample_workbook() -> bytes:
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        wti = _sheet_with_series(
            "WTIPUUS", "West Texas Intermediate Spot Average", [70, 71, 72, 73]
        )
        wti.to_excel(
            writer,
            sheet_name="2tab",
            header=False,
            index=False,
        )
        production = _sheet_with_series(
            "COPRPUS",
            "U.S. total crude oil production",
            [13, 14, 15, 16],
        )
        production.to_excel(
            writer,
            sheet_name="4atab",
            header=False,
            index=False,
        )
    return bio.getvalue()


def test_parse_archive_index_extracts_xlsx_issues_only() -> None:
    issues = parse_archive_index(_sample_archive_html().decode("utf-8"))

    assert len(issues) == 1
    assert issues[0] == STEOArchiveIssue(
        issue_label="2026-04",
        issue_year=2026,
        issue_month=4,
        release_date=date(2026, 4, 7),
        href="archives/apr26_base.xlsx",
    )


def test_parse_steo_workbook_extracts_selected_long_panel() -> None:
    issue = STEOArchiveIssue(
        issue_label="2026-04",
        issue_year=2026,
        issue_month=4,
        release_date=date(2026, 4, 7),
        href="archives/apr26_base.xlsx",
    )

    frame = parse_steo_workbook(_sample_workbook(), issue)

    assert {"WTIPUUS", "COPRPUS"} <= set(frame["series_code"])
    assert set(frame["sheet_name"]) == {"2tab", "4atab"}
    assert frame["forecast_value"].notna().all()
    wti = frame[frame["series_code"] == "WTIPUUS"].sort_values("observation_month")
    assert list(wti["forecast_month_offset"]) == [-3, -2, -1, 0]
    assert list(wti["forecast_value"]) == [70.0, 71.0, 72.0, 73.0]


def test_fetch_downloads_archive_and_emits_true_first_release(writer_and_manifest) -> None:
    w, m, _ = writer_and_manifest
    workbook = _sample_workbook()
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        if str(request.url) == ARCHIVE_INDEX_URL:
            return httpx.Response(200, content=_sample_archive_html())
        if str(request.url).endswith("/archives/apr26_base.xlsx"):
            return httpx.Response(200, content=workbook)
        raise AssertionError(f"unexpected URL: {request.url}")

    http = _build_http_client(handler)
    ing = EIASTEOValueArchiveIngester(
        w,
        m,
        http=http,
        since=date(2026, 1, 1),
        until=date(2026, 12, 31),
    )

    results = ing.fetch(as_of_ts=datetime(2026, 4, 29, tzinfo=UTC))

    assert len(results) == 1
    fr = results[0]
    assert requested[0] == ARCHIVE_INDEX_URL
    assert fr.source == "eia_steo"
    assert fr.dataset == "steo_value_archive"
    assert fr.series == "steo_forecast_panel"
    assert fr.release_ts == datetime(2026, 4, 7, 16, 0, tzinfo=UTC)
    assert fr.usable_after_ts == datetime(2026, 4, 7, 16, 5, tzinfo=UTC)
    assert fr.vintage_quality == "true_first_release"
    assert len(fr.data) == 8
    assert fr.provenance["workbook_url"].endswith("archives/apr26_base.xlsx")


def test_ingest_writes_manifest_row(writer_and_manifest) -> None:
    w, m, tmp_path = writer_and_manifest
    workbook = _sample_workbook()

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == ARCHIVE_INDEX_URL:
            return httpx.Response(200, content=_sample_archive_html())
        if str(request.url).endswith("/archives/apr26_base.xlsx"):
            return httpx.Response(200, content=workbook)
        raise AssertionError(f"unexpected URL: {request.url}")

    http = _build_http_client(handler)
    ing = EIASTEOValueArchiveIngester(
        w,
        m,
        http=http,
        since=date(2026, 1, 1),
        until=date(2026, 12, 31),
    )

    writes = ing.ingest(as_of_ts=datetime(2026, 4, 29, tzinfo=UTC))

    assert len(writes) == 1
    rows = m.list_all(source="eia_steo")
    value_rows = [r for r in rows if r.dataset == "steo_value_archive"]
    assert len(value_rows) == 1
    parquet_path = tmp_path / value_rows[0].parquet_path
    assert parquet_path.exists()
    payload = pd.read_parquet(parquet_path)
    assert set(payload["series_code"]) == {"WTIPUUS", "COPRPUS"}
