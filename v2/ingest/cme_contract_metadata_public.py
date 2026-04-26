"""CME public CL contract-metadata ingester (METADATA ONLY).

This ingester scrapes the public CME Group product pages for
Light Sweet Crude Oil (CL) and emits ONLY contract specification
metadata and the last-trade-date calendar. It MUST NOT write any
column resembling a price, quote, settlement, bid, ask, volume, or
open interest. CME-direct quote data is NOT public-rights and must
not flow through this module.

Pages scraped:
    * Contract specs:
      ``https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html``
    * Calendar (last-trade-dates):
      ``https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.calendar.html``

Emits two FetchResults:
    1. ``series="cl_contract_spec"`` — long-form ``[field, value, retrieved_at_utc]``.
    2. ``series="cl_expiry_calendar"`` — ``[contract_month, last_trade_date, retrieved_at_utc]``.

Rights enforcement: before returning, ``fetch()`` checks every output
column name against a forbidden-pattern regex. Any match raises
:class:`CMERightsViolation`. The pattern is anchored such that
``last_trade_date`` and ``last_trade_rule`` PASS but a column literally
named ``last``, ``settle``, ``settle_price``, etc., is rejected.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Any

import pandas as pd

from v2.ingest._http import HTTPClient
from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.writer import PITWriter

CME_CL_SPEC_URL = (
    "https://www.cmegroup.com/markets/energy/crude-oil/"
    "light-sweet-crude.contractSpecs.html"
)
CME_CL_CALENDAR_URL = (
    "https://www.cmegroup.com/markets/energy/crude-oil/"
    "light-sweet-crude.calendar.html"
)
SCRAPER_VERSION = "v2.b2b.0"


# Forbidden-column pattern: matches exact tokens (price, settle,
# settlement, quote, bid, ask, volume, open_interest, oi) AND the
# suffixes ``_price``, ``_settle``, ``_quote`` so e.g. ``close_price``
# and ``bid_quote`` are caught. Critically does NOT match
# ``last_trade_date`` or ``last_trade_rule``.
FORBIDDEN_COLUMN_RE = re.compile(
    r"^(price|settle|settlement|quote|bid|ask|volume|open_interest|oi)$"
    r"|(_price$|_settle$|_quote$)",
    re.IGNORECASE,
)


class CMERightsViolation(RuntimeError):  # noqa: N818 — name is contract-mandated by Wave 1 plan
    """A FetchResult contained a forbidden price/quote/settlement column.

    Raised pre-write inside :meth:`CMEContractMetadataIngester.fetch` so
    that no rights-restricted column can ever reach the PIT store.
    """


class CMEScrapeError(ValueError):
    """The CME page could not be parsed into the expected shape."""


class _TextStripper(HTMLParser):
    """Collect visible text from an HTML document, preserving rough
    block boundaries with newlines."""

    # Tags that force a NEWLINE boundary (one row per line).
    _BLOCK_TAGS = {
        "br",
        "p",
        "tr",
        "li",
        "div",
        "section",
        "article",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
    # Tags that force a SPACE boundary (cell separator within a row).
    _INLINE_BREAK_TAGS = {"td", "th"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")
        elif tag in self._INLINE_BREAK_TAGS:
            self._chunks.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self._BLOCK_TAGS:
            self._chunks.append("\n")
        elif tag in self._INLINE_BREAK_TAGS:
            self._chunks.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        joined = "".join(self._chunks)
        # Collapse runs of whitespace per-line, drop empty lines.
        lines: list[str] = []
        for raw in joined.splitlines():
            cleaned = re.sub(r"[ \t\r\f\v]+", " ", raw).strip()
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)


def _strip_html(html: str) -> str:
    parser = _TextStripper()
    parser.feed(html)
    return parser.text()


def _parse_last_modified(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(UTC)
    if dt is None:
        return datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


# -- spec-page parsing -------------------------------------------------------


_SPEC_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "contract_unit": re.compile(
        r"contract\s*unit\s*[:\-]?\s*(?P<value>[^\n]+)", re.IGNORECASE
    ),
    "settlement_method": re.compile(
        r"settlement\s*method\s*[:\-]?\s*(?P<value>[^\n]+)", re.IGNORECASE
    ),
    "last_trade_rule": re.compile(
        r"termination\s*of\s*trading\s*[:\-]?\s*(?P<value>[^\n]+(?:\n[^\n]+){0,3})",
        re.IGNORECASE,
    ),
    "trading_hours_text": re.compile(
        r"trading\s*hours?\s*[:\-]?\s*(?P<value>[^\n]+(?:\n[^\n]+){0,3})",
        re.IGNORECASE,
    ),
}


def _parse_spec_page(html: str) -> dict[str, str]:
    """Best-effort extraction of contract-spec key/value pairs."""
    text = _strip_html(html)
    out: dict[str, str] = {}
    for field, pat in _SPEC_FIELD_PATTERNS.items():
        m = pat.search(text)
        if m is None:
            continue
        value = m.group("value").strip()
        # Trim trailing colons / labels accidentally captured.
        value = re.sub(r"\s+", " ", value)
        if value:
            out[field] = value
    if not out:
        raise CMEScrapeError(
            "CME spec page yielded no parseable fields; "
            "page layout may have changed"
        )
    return out


# -- calendar-page parsing ---------------------------------------------------


_MONTH_NAME_RE = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_CONTRACT_MONTH_RE = re.compile(
    rf"(?P<month>{_MONTH_NAME_RE})\s+(?P<year>\d{{4}})", re.IGNORECASE
)
_ISO_DATE_RE = re.compile(r"(?P<date>\d{4}-\d{2}-\d{2})")
_LONG_DATE_RE = re.compile(
    rf"(?P<day>\d{{1,2}})\s+(?P<month>{_MONTH_NAME_RE})\s+(?P<year>\d{{4}})",
    re.IGNORECASE,
)

_MONTH_NUM = {
    name: i
    for i, name in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ],
        start=1,
    )
}


def _short_month(name: str) -> str:
    return name[:3].lower()


def _parse_calendar_page(html: str) -> list[tuple[str, str]]:
    """Return list of (contract_month, last_trade_date) pairs.

    ``contract_month`` is normalised to ``YYYY-MM`` and
    ``last_trade_date`` to ``YYYY-MM-DD``.
    """
    text = _strip_html(html)
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Process line-by-line; calendar tables typically render one
    # contract per row.
    for line in text.splitlines():
        cm_match = _CONTRACT_MONTH_RE.search(line)
        if cm_match is None:
            continue
        month_name = cm_match.group("month")
        year = cm_match.group("year")
        cm_key = f"{year}-{_MONTH_NUM[_short_month(month_name)]:02d}"
        if cm_key in seen:
            continue

        # Look for a date AFTER the contract-month token on the same line.
        tail = line[cm_match.end():]
        ltd: str | None = None
        iso = _ISO_DATE_RE.search(tail)
        if iso:
            ltd = iso.group("date")
        else:
            long_m = _LONG_DATE_RE.search(tail)
            if long_m:
                d = int(long_m.group("day"))
                m = _MONTH_NUM[_short_month(long_m.group("month"))]
                y = int(long_m.group("year"))
                ltd = f"{y:04d}-{m:02d}-{d:02d}"
        if ltd is None:
            continue
        pairs.append((cm_key, ltd))
        seen.add(cm_key)

    if not pairs:
        raise CMEScrapeError(
            "CME calendar page yielded no (contract_month, last_trade_date) rows"
        )
    return pairs


# -- ingester ----------------------------------------------------------------


def _check_rights(results: list[FetchResult]) -> None:
    """Raise :class:`CMERightsViolation` if any output column matches the
    forbidden pattern."""
    for fr in results:
        bad = [c for c in fr.data.columns if FORBIDDEN_COLUMN_RE.search(str(c))]
        if bad:
            raise CMERightsViolation(
                f"forbidden columns in series={fr.series!r}: {bad}"
            )


class CMEContractMetadataIngester(BaseIngester):
    """CME public CL contract-metadata scraper (metadata-only)."""

    name = "cme_cl_metadata"
    source = "cme_cl_metadata"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        http: HTTPClient | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        self._http_owned = http is None
        self._http = http if http is not None else HTTPClient()

    # -- public --------------------------------------------------------------

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        spec_resp = self._http.get(CME_CL_SPEC_URL)
        cal_resp = self._http.get(CME_CL_CALENDAR_URL)

        if spec_resp.status_code != 200:
            raise CMEScrapeError(
                f"CME spec page HTTP {spec_resp.status_code}"
            )
        if cal_resp.status_code != 200:
            raise CMEScrapeError(
                f"CME calendar page HTTP {cal_resp.status_code}"
            )

        spec_html = spec_resp.content.decode("utf-8", errors="replace")
        cal_html = cal_resp.content.decode("utf-8", errors="replace")

        spec_fields = _parse_spec_page(spec_html)
        calendar_rows = _parse_calendar_page(cal_html)

        spec_release_ts = _parse_last_modified(spec_resp.last_modified)
        cal_release_ts = _parse_last_modified(cal_resp.last_modified)

        spec_df = pd.DataFrame(
            {
                "field": list(spec_fields.keys()),
                "value": list(spec_fields.values()),
                "retrieved_at_utc": pd.Series(
                    [spec_resp.retrieved_at_utc] * len(spec_fields),
                    dtype="datetime64[ns, UTC]",
                ),
            }
        )

        cal_df = pd.DataFrame(
            {
                "contract_month": [cm for cm, _ in calendar_rows],
                "last_trade_date": [
                    pd.to_datetime(ltd).date() for _, ltd in calendar_rows
                ],
                "retrieved_at_utc": pd.Series(
                    [cal_resp.retrieved_at_utc] * len(calendar_rows),
                    dtype="datetime64[ns, UTC]",
                ),
            }
        )

        spec_provenance: dict[str, Any] = {
            "source": self.source,
            "method": "html_scrape",
            "scraper_version": SCRAPER_VERSION,
            "endpoint": CME_CL_SPEC_URL,
            "etag": spec_resp.etag,
            "last_modified": spec_resp.last_modified,
            "retrieved_at_utc": spec_resp.retrieved_at_utc.isoformat(),
            "rights_status": "public_metadata_only",
        }
        cal_provenance: dict[str, Any] = {
            "source": self.source,
            "method": "html_scrape",
            "scraper_version": SCRAPER_VERSION,
            "endpoint": CME_CL_CALENDAR_URL,
            "etag": cal_resp.etag,
            "last_modified": cal_resp.last_modified,
            "retrieved_at_utc": cal_resp.retrieved_at_utc.isoformat(),
            "rights_status": "public_metadata_only",
        }

        results = [
            FetchResult(
                source=self.source,
                series="cl_contract_spec",
                release_ts=spec_release_ts,
                revision_ts=None,
                data=spec_df,
                provenance=spec_provenance,
            ),
            FetchResult(
                source=self.source,
                series="cl_expiry_calendar",
                release_ts=cal_release_ts,
                revision_ts=None,
                data=cal_df,
                provenance=cal_provenance,
            ),
        ]

        # Rights enforcement (last line of defense before write).
        _check_rights(results)
        return results

    def close(self) -> None:
        if self._http_owned:
            self._http.close()


__all__ = [
    "CME_CL_CALENDAR_URL",
    "CME_CL_SPEC_URL",
    "FORBIDDEN_COLUMN_RE",
    "CMEContractMetadataIngester",
    "CMERightsViolation",
    "CMEScrapeError",
]
