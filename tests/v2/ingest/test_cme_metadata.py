"""Tests for CMEContractMetadataIngester (Phase B2b Wave 1, agent A4.2).

Rights guardrail is the most important test: the writer code path
MUST NOT permit any column resembling price/quote/settlement.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pandas as pd
import pytest

from v2.ingest._http import HTTPClient
from v2.ingest.base import FetchResult
from v2.ingest.cme_contract_metadata_public import (
    CME_CL_CALENDAR_URL,
    CME_CL_SPEC_URL,
    FORBIDDEN_COLUMN_RE,
    CMEContractMetadataIngester,
    CMERightsViolation,
    _check_rights,
)
from v2.pit_store.manifest import open_manifest
from v2.pit_store.writer import PITWriter

SPEC_HTML = """
<html><body>
<h1>Light Sweet Crude Oil Futures - Contract Specs</h1>
<table>
  <tr><td>Contract Unit</td><td>1,000 barrels</td></tr>
  <tr><td>Settlement Method</td><td>Physical Delivery</td></tr>
  <tr><td>Trading Hours</td><td>Sunday-Friday 6:00 p.m. - 5:00 p.m. ET</td></tr>
  <tr><td>Termination of Trading</td>
      <td>Trading terminates 3 business days before the 25th calendar day</td></tr>
</table>
</body></html>
"""

CALENDAR_HTML = """
<html><body>
<table id="calendar">
  <tr><th>Contract Month</th><th>Last Trade Date</th></tr>
  <tr><td>May 2026</td><td>2026-04-22</td></tr>
  <tr><td>June 2026</td><td>2026-05-20</td></tr>
  <tr><td>July 2026</td><td>2026-06-22</td></tr>
  <tr><td>August 2026</td><td>2026-07-21</td></tr>
</table>
</body></html>
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


def _two_page_handler(
    *,
    spec_html: str = SPEC_HTML,
    calendar_html: str = CALENDAR_HTML,
    spec_last_modified: str | None = "Wed, 23 Apr 2026 12:00:00 GMT",
    calendar_last_modified: str | None = "Thu, 24 Apr 2026 06:00:00 GMT",
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "contractSpecs" in url:
            headers: dict[str, str] = {"Content-Type": "text/html; charset=utf-8"}
            if spec_last_modified is not None:
                headers["Last-Modified"] = spec_last_modified
            return httpx.Response(
                200, content=spec_html.encode("utf-8"), headers=headers
            )
        if "calendar" in url:
            headers = {"Content-Type": "text/html; charset=utf-8"}
            if calendar_last_modified is not None:
                headers["Last-Modified"] = calendar_last_modified
            return httpx.Response(
                200, content=calendar_html.encode("utf-8"), headers=headers
            )
        return httpx.Response(404, json={"error": f"no route for {url!r}"})

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
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_spec_and_calendar(writer_and_manifest):
    w, m, _ = writer_and_manifest
    http = _build_http_client(_two_page_handler())
    ing = CMEContractMetadataIngester(w, m, http=http)
    results = ing.fetch()

    assert len(results) == 2
    spec = next(r for r in results if r.series == "cl_contract_spec")
    cal = next(r for r in results if r.series == "cl_expiry_calendar")

    assert list(spec.data.columns) == ["field", "value", "retrieved_at_utc"]
    fields = set(spec.data["field"].tolist())
    # We require at least 4 rows.
    assert len(fields) >= 4
    assert "contract_unit" in fields
    assert "settlement_method" in fields
    assert "last_trade_rule" in fields
    assert "trading_hours_text" in fields

    assert list(cal.data.columns) == [
        "contract_month",
        "last_trade_date",
        "retrieved_at_utc",
    ]
    assert len(cal.data) >= 3
    # The May 2026 row should map to 2026-04-22.
    may_row = cal.data[cal.data["contract_month"] == "2026-05"].iloc[0]
    assert str(may_row["last_trade_date"]) == "2026-04-22"


# ---------------------------------------------------------------------------
# Rights guardrail (most important)
# ---------------------------------------------------------------------------


def test_rights_guardrail_rejects_settle_price():
    """A FetchResult with a forbidden column must raise CMERightsViolation."""
    bad_df = pd.DataFrame(
        {
            "contract_month": ["2026-05"],
            "settle_price": [82.5],
            "retrieved_at_utc": pd.Series(
                [datetime.now(UTC)], dtype="datetime64[ns, UTC]"
            ),
        }
    )
    fr = FetchResult(
        source="cme_cl_metadata",
        series="cl_expiry_calendar",
        release_ts=datetime.now(UTC),
        revision_ts=None,
        data=bad_df,
        provenance={"source": "cme_cl_metadata", "method": "html_scrape"},
    )
    with pytest.raises(CMERightsViolation):
        _check_rights([fr])


def test_rights_guardrail_allows_last_trade_date():
    """The legitimate last_trade_date column MUST NOT be flagged."""
    ok_df = pd.DataFrame(
        {
            "contract_month": ["2026-05"],
            "last_trade_date": [pd.to_datetime("2026-04-22").date()],
            "retrieved_at_utc": pd.Series(
                [datetime.now(UTC)], dtype="datetime64[ns, UTC]"
            ),
        }
    )
    fr = FetchResult(
        source="cme_cl_metadata",
        series="cl_expiry_calendar",
        release_ts=datetime.now(UTC),
        revision_ts=None,
        data=ok_df,
        provenance={"source": "cme_cl_metadata", "method": "html_scrape"},
    )
    # Should not raise.
    _check_rights([fr])


@pytest.mark.parametrize(
    "col",
    [
        "price",
        "settle",
        "settlement",
        "quote",
        "bid",
        "ask",
        "volume",
        "open_interest",
        "oi",
        "close_price",
        "bid_quote",
    ],
)
def test_forbidden_column_names_are_blocked(col):
    assert FORBIDDEN_COLUMN_RE.search(col), (
        f"column {col!r} should be flagged by FORBIDDEN_COLUMN_RE"
    )


@pytest.mark.parametrize(
    "col",
    [
        "last_trade_date",
        "last_trade_rule",
        "expiration_rule",
        "contract_unit",
    ],
)
def test_legit_column_names_are_allowed(col):
    assert not FORBIDDEN_COLUMN_RE.search(col), (
        f"column {col!r} should NOT be flagged"
    )


# ---------------------------------------------------------------------------
# release_ts handling
# ---------------------------------------------------------------------------


def test_release_ts_parsed_from_last_modified(writer_and_manifest):
    w, m, _ = writer_and_manifest
    http = _build_http_client(_two_page_handler())
    ing = CMEContractMetadataIngester(w, m, http=http)
    results = ing.fetch()
    spec = next(r for r in results if r.series == "cl_contract_spec")
    assert spec.release_ts == datetime(2026, 4, 23, 12, 0, tzinfo=UTC)


def test_release_ts_falls_back_to_now_when_header_absent(writer_and_manifest):
    w, m, _ = writer_and_manifest
    before = datetime.now(UTC)
    http = _build_http_client(
        _two_page_handler(spec_last_modified=None, calendar_last_modified=None)
    )
    ing = CMEContractMetadataIngester(w, m, http=http)
    results = ing.fetch()
    after = datetime.now(UTC)
    for fr in results:
        assert before <= fr.release_ts <= after


# ---------------------------------------------------------------------------
# End-to-end ingest
# ---------------------------------------------------------------------------


def test_ingest_writes_two_manifest_rows(writer_and_manifest):
    w, m, _ = writer_and_manifest
    http = _build_http_client(_two_page_handler())
    ing = CMEContractMetadataIngester(w, m, http=http)
    written = ing.ingest()
    assert len(written) == 2
    rows = m.list_all(source="cme_cl_metadata")
    assert len(rows) == 2
    assert {r.series for r in rows} == {"cl_contract_spec", "cl_expiry_calendar"}


def test_endpoint_constants_target_cme():
    assert CME_CL_SPEC_URL.startswith("https://www.cmegroup.com/")
    assert CME_CL_CALENDAR_URL.startswith("https://www.cmegroup.com/")
    assert "contractSpecs" in CME_CL_SPEC_URL
    assert "calendar" in CME_CL_CALENDAR_URL
