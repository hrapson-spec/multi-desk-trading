"""Tests for first-release EIA WPSR archive restoration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime

import httpx
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.eia_wpsr_archive import (
    EIAWPSRArchiveIngester,
    WPSRSeriesMapping,
    extract_mapping_value,
    parse_archive_issue_links,
    parse_issue_csv_links,
    parse_issue_dates,
    read_wpsr_csv,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter

Handler = Callable[[httpx.Request], httpx.Response]


ISSUE_URL = (
    "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
    "2024_06_20/wpsr_2024_06_20.php"
)

ISSUE_HTML = """
<html>
<p>
Data for week ending June 14, 2024&nbsp;&nbsp;|&nbsp;&nbsp;
<strong>Release Date:</strong>&nbsp;
June 20, 2024
</p>
<a href="csv/table1.csv">CSV</a>
<a href="csv/table2.csv">CSV</a>
<a href="csv/table4.csv">CSV</a>
</html>
"""

INDEX_HTML = f"""
<a href="/petroleum/supply/weekly/archive/2024/2024_06_20/wpsr_2024_06_20.php">20</a>
<a href="{ISSUE_URL}">duplicate absolute</a>
<a href="/petroleum/supply/weekly/archive/2024/2024_06_26/wpsr_2024_06_26.php">26</a>
"""

TABLE1 = b'''"STUB_1","6/14/24","6/7/24","Difference"
"Crude Oil","828.017","830.178","-2.161"
"STUB_1","STUB_2","6/14/24","6/7/24","Difference"
"Crude Oil Supply ","(1)     Domestic Production","13,200","13,200","0"
"Crude Oil Supply ","(8)        Imports","7,054","8,304","-1,250"
"Crude Oil Supply ","(12)        Exports","4,418","3,188","1,230"
"Products Supplied ","(29)   Total","20,123","20,000","123"
'''

TABLE2 = b'''"STUB_1","STUB_2","6/14/24","6/7/24","Difference"
"Refiner Inputs and Utilization ","Crude Oil Inputs","16,765","17,047","-281"
"Refiner Inputs and Utilization ","Percent Utilization","93.5","95.0","-1.5"
'''

TABLE4 = b'''"STUB_1","6/14/24","6/7/24","Difference"
"Crude Oil","828.017","830.178","-2.161"
"Commercial (Excluding SPR)","457.105","459.652","-2.547"
"Cushing","33.321","34.000","-0.679"
"SPR","370.912","370.526","0.386"
"Total Motor Gasoline","231.232","233.512","-2.280"
"Kerosene-Type Jet Fuel","41.947","42.003","-0.055"
"Distillate Fuel Oil","121.640","123.366","-1.726"
"Propane/Propylene","71.443","69.808","1.635"
'''


def _http_client(routes: dict[str, bytes | str]) -> HTTPClient:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        body = routes.get(url)
        if body is None:
            return httpx.Response(404, content=b"not found")
        content = body.encode("utf-8") if isinstance(body, str) else body
        return httpx.Response(200, content=content)

    client = HTTPClient()
    client._client.close()
    client._client = httpx.Client(transport=httpx.MockTransport(handler))
    return client


@pytest.fixture
def writer_and_manifest(tmp_path):
    manifest = open_manifest(tmp_path)
    writer = PITWriter(tmp_path, manifest)
    try:
        yield writer, manifest, tmp_path
    finally:
        manifest.close()


def test_parse_archive_issue_links_dedupes_and_absolutises():
    urls = parse_archive_issue_links(
        INDEX_HTML,
        base_url="https://www.eia.gov/petroleum/supply/weekly/archive/",
    )
    assert urls == [
        ISSUE_URL,
        (
            "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
            "2024_06_26/wpsr_2024_06_26.php"
        ),
    ]


def test_parse_issue_metadata_and_csv_links():
    release_date, week_ending = parse_issue_dates(ISSUE_HTML)
    links = parse_issue_csv_links(ISSUE_HTML, base_url=ISSUE_URL)
    assert release_date == date(2024, 6, 20)
    assert week_ending == date(2024, 6, 14)
    assert links["table4"] == (
        "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
        "2024_06_20/csv/table4.csv"
    )


def test_extract_mapping_value_handles_table_sections_and_units():
    table1 = read_wpsr_csv(TABLE1)
    table4 = read_wpsr_csv(TABLE4)
    assert extract_mapping_value(
        table4,
        WPSRSeriesMapping(
            "WCESTUS1", "table4", "Commercial (Excluding SPR)", "kbbl", 1000.0
        ),
    ) == pytest.approx(457.105)
    assert extract_mapping_value(
        table1,
        WPSRSeriesMapping(
            "WCRIMUS2", "table1", "Imports", "kbbl/d", section="Crude Oil Supply"
        ),
    ) == pytest.approx(7054.0)


def test_archive_ingester_fetches_true_first_release_series(writer_and_manifest):
    writer, manifest, _ = writer_and_manifest
    http = _http_client(
        {
            ISSUE_URL: ISSUE_HTML,
            (
                "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
                "2024_06_20/csv/table1.csv"
            ): TABLE1,
            (
                "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
                "2024_06_20/csv/table2.csv"
            ): TABLE2,
            (
                "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
                "2024_06_20/csv/table4.csv"
            ): TABLE4,
        }
    )
    ingester = EIAWPSRArchiveIngester(
        writer,
        manifest,
        issue_urls=[ISSUE_URL],
        series_ids=["WCESTUS1", "WCRFPUS2", "WPULEUS3"],
        http=http,
    )

    results = ingester.fetch()

    by_series = {r.series: r for r in results}
    assert set(by_series) == {"WCESTUS1", "WCRFPUS2", "WPULEUS3"}
    crude_stocks = by_series["WCESTUS1"]
    assert crude_stocks.source == "eia"
    assert crude_stocks.dataset == "wpsr"
    assert crude_stocks.release_ts == datetime(2024, 6, 20, 14, 30, tzinfo=UTC)
    assert crude_stocks.usable_after_ts == datetime(2024, 6, 20, 14, 35, tzinfo=UTC)
    assert crude_stocks.vintage_quality == "true_first_release"
    assert crude_stocks.data["value"].iloc[0] == pytest.approx(457_105.0)
    assert by_series["WCRFPUS2"].data["value"].iloc[0] == pytest.approx(13_200.0)
    assert by_series["WPULEUS3"].data["value"].iloc[0] == pytest.approx(93.5)


def test_archive_ingester_skips_duplicate_issue_metadata(writer_and_manifest):
    writer, manifest, _ = writer_and_manifest
    duplicate_url = (
        "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
        "2024_06_21/wpsr_2024_06_21.php"
    )
    http = _http_client(
        {
            ISSUE_URL: ISSUE_HTML,
            duplicate_url: ISSUE_HTML,
            (
                "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
                "2024_06_20/csv/table4.csv"
            ): TABLE4,
        }
    )
    ingester = EIAWPSRArchiveIngester(
        writer,
        manifest,
        issue_urls=[ISSUE_URL, duplicate_url],
        series_ids=["WCESTUS1"],
        http=http,
    )

    results = ingester.fetch()

    assert len(results) == 1
    assert results[0].series == "WCESTUS1"
    assert ingester.last_run_failed_issues == [
        (
            duplicate_url,
            "duplicate_issue_metadata_skipped:"
            "release_date=2024-06-20,week_ending=2024-06-14",
        )
    ]


def test_archive_ingest_writes_pit_vintage_with_latency_guard(writer_and_manifest):
    writer, manifest, pit_root = writer_and_manifest
    http = _http_client(
        {
            ISSUE_URL: ISSUE_HTML,
            (
                "https://www.eia.gov/petroleum/supply/weekly/archive/2024/"
                "2024_06_20/csv/table4.csv"
            ): TABLE4,
        }
    )
    ingester = EIAWPSRArchiveIngester(
        writer,
        manifest,
        issue_urls=[ISSUE_URL],
        series_ids=["WCESTUS1"],
        http=http,
    )
    [written] = ingester.ingest()
    reader = PITReader(pit_root, manifest)

    before = reader.as_of(
        "eia",
        "WCESTUS1",
        datetime(2024, 6, 20, 14, 34, 59, tzinfo=UTC),
        dataset="wpsr",
    )
    after = reader.as_of(
        "eia",
        "WCESTUS1",
        datetime(2024, 6, 20, 14, 35, 1, tzinfo=UTC),
        dataset="wpsr",
    )

    assert written.vintage_quality == "true_first_release"
    assert before is None
    assert after is not None
    assert after.manifest.dataset == "wpsr"
    assert after.manifest.vintage_quality == "true_first_release"
    assert after.data["value"].iloc[0] == pytest.approx(457_105.0)
