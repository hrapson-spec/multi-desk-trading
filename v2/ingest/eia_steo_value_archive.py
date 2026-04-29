"""EIA STEO archived Excel value ingester (v1.1).

Pulls the official STEO archive index, downloads monthly ``*_base.xlsx``
workbooks, and emits a narrow long-form forecast panel for selected
oil-market series. This upgrades the prior calendar-only STEO event feed with
value-bearing PIT vintages suitable for forecast-revision features.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html import unescape
from zoneinfo import ZoneInfo

import pandas as pd

from v2.ingest._http import HTTPClient, RetryExhaustedError
from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.quality import VintageQuality
from v2.pit_store.writer import PITWriter

NY = ZoneInfo("America/New_York")
SCRAPER_VERSION = "v2.eia_steo_value_archive.0"
ARCHIVE_INDEX_URL = "https://www.eia.gov/outlooks/steo/outlook.php"
ARCHIVE_BASE_URL = "https://www.eia.gov/outlooks/steo/"
RELEASE_TIME_ET = time(12, 0)
LATENCY_GUARD_MINUTES = 5

MONTH_NAME_TO_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

SERIES_BY_SHEET: dict[str, frozenset[str]] = {
    "2tab": frozenset(("WTIPUUS", "BREPUUS")),
    "3atab": frozenset(("papr_world", "patc_world", "copr_world")),
    "3dtab": frozenset(("copr_world", "copr_opecplus", "coprpus")),
    "3etab": frozenset(("patc_world", "patc_oecd", "patc_non_oecd")),
    "4atab": frozenset(("COPRPUS",)),
}


@dataclass(frozen=True)
class STEOArchiveIssue:
    issue_label: str
    issue_year: int
    issue_month: int
    release_date: date
    href: str


def _strip_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", value)
    return " ".join(unescape(without_tags).split())


def parse_archive_index(html: str) -> list[STEOArchiveIssue]:
    """Parse EIA's STEO archive table into issue metadata."""
    row_re = re.compile(r"<tr[^>]*>(.*?)</tr>", flags=re.IGNORECASE | re.DOTALL)
    td_re = re.compile(r"<td[^>]*>(.*?)</td>", flags=re.IGNORECASE | re.DOTALL)
    href_re = re.compile(r'href="([^"]*?_base\.xlsx?)"', flags=re.IGNORECASE)

    issues: list[STEOArchiveIssue] = []
    for row_match in row_re.finditer(html):
        row_html = row_match.group(1)
        href_match = href_re.search(row_html)
        if href_match is None:
            continue
        href = unescape(href_match.group(1))
        if not href.lower().endswith(".xlsx"):
            continue

        cells = [_strip_html(c.group(1)) for c in td_re.finditer(row_html)]
        if len(cells) < 2:
            continue

        issue_ts = pd.to_datetime(cells[0], errors="coerce")
        release_ts = pd.to_datetime(cells[1], errors="coerce")
        if pd.isna(issue_ts) or pd.isna(release_ts):
            continue

        issue_date = issue_ts.date()
        release_date = release_ts.date()
        issues.append(
            STEOArchiveIssue(
                issue_label=f"{issue_date.year}-{issue_date.month:02d}",
                issue_year=issue_date.year,
                issue_month=issue_date.month,
                release_date=release_date,
                href=href,
            )
        )

    issues.sort(key=lambda x: x.release_date)
    return issues


def _release_ts_utc(release_date: date) -> datetime:
    return datetime.combine(release_date, RELEASE_TIME_ET, tzinfo=NY).astimezone(UTC)


def _archive_url(href: str) -> str:
    if href.startswith("http://") or href.startswith("https://"):
        return href
    return ARCHIVE_BASE_URL + href.lstrip("/")


def _month_columns(sheet: pd.DataFrame) -> list[tuple[int, date]]:
    years = sheet.iloc[2] if len(sheet) > 2 else pd.Series(dtype=object)
    months = sheet.iloc[3] if len(sheet) > 3 else pd.Series(dtype=object)
    current_year: int | None = None
    out: list[tuple[int, date]] = []
    for col in range(2, sheet.shape[1]):
        year_val = years.iloc[col]
        if pd.notna(year_val):
            try:
                current_year = int(float(year_val))
            except (TypeError, ValueError):
                current_year = None
        month_key = str(months.iloc[col]).strip().lower()[:3]
        month_num = MONTH_NAME_TO_NUM.get(month_key)
        if current_year is None or month_num is None:
            continue
        out.append((col, date(current_year, month_num, 1)))
    return out


def parse_steo_workbook(content: bytes, issue: STEOArchiveIssue) -> pd.DataFrame:
    """Parse selected STEO workbook rows into a long-form forecast panel."""
    excel = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
    records: list[dict[str, object]] = []

    issue_month_index = issue.issue_year * 12 + issue.issue_month
    for sheet_name, wanted_codes in SERIES_BY_SHEET.items():
        if sheet_name not in excel.sheet_names:
            continue
        sheet = pd.read_excel(excel, sheet_name=sheet_name, header=None)
        month_cols = _month_columns(sheet)
        if not month_cols:
            continue

        for row_idx in range(4, len(sheet)):
            code_raw = sheet.iloc[row_idx, 0]
            if pd.isna(code_raw):
                continue
            series_code = str(code_raw).strip()
            if series_code not in wanted_codes:
                continue
            series_label = (
                "" if pd.isna(sheet.iloc[row_idx, 1]) else str(sheet.iloc[row_idx, 1]).strip()
            )
            for col, observation_month in month_cols:
                value = pd.to_numeric(sheet.iloc[row_idx, col], errors="coerce")
                if pd.isna(value):
                    continue
                obs_month_index = observation_month.year * 12 + observation_month.month
                records.append(
                    {
                        "issue_label": issue.issue_label,
                        "issue_year": issue.issue_year,
                        "issue_month": issue.issue_month,
                        "release_date": issue.release_date,
                        "sheet_name": sheet_name,
                        "series_code": series_code,
                        "series_label": series_label,
                        "observation_month": observation_month,
                        "forecast_month_offset": obs_month_index - issue_month_index,
                        "forecast_value": float(value),
                    }
                )

    if not records:
        raise ValueError(f"no selected STEO series found in {issue.href}")

    return pd.DataFrame.from_records(records).sort_values(
        ["sheet_name", "series_code", "observation_month"]
    )


class EIASTEOValueArchiveIngester(BaseIngester):
    """Fetch official STEO archived Excel forecast values into the PIT store."""

    name = "eia_steo_value_archive"
    source = "eia_steo"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        http: HTTPClient | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        self._http = http if http is not None else HTTPClient()
        self._owns_http = http is None
        self._since = since if since is not None else date(2020, 1, 1)
        self._until = until if until is not None else date.today()

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        del as_of_ts
        try:
            index_resp = self._http.get(ARCHIVE_INDEX_URL)
        except RetryExhaustedError as exc:
            raise RuntimeError(f"STEO archive index fetch failed: {exc!r}") from exc
        if not index_resp.content:
            raise RuntimeError("STEO archive index returned empty body")

        issues = [
            issue
            for issue in parse_archive_index(index_resp.content.decode("utf-8", errors="replace"))
            if self._since <= issue.release_date <= self._until
        ]

        results: list[FetchResult] = []
        for issue in issues:
            url = _archive_url(issue.href)
            try:
                workbook_resp = self._http.get(url)
            except RetryExhaustedError as exc:
                raise RuntimeError(f"STEO workbook fetch failed for {url}: {exc!r}") from exc
            if not workbook_resp.content:
                raise RuntimeError(f"STEO workbook returned empty body: {url}")
            data = parse_steo_workbook(workbook_resp.content, issue)
            release_ts = _release_ts_utc(issue.release_date)
            usable_after_ts = release_ts + timedelta(minutes=LATENCY_GUARD_MINUTES)
            results.append(
                FetchResult(
                    source=self.source,
                    dataset="steo_value_archive",
                    series="steo_forecast_panel",
                    release_ts=release_ts,
                    usable_after_ts=usable_after_ts,
                    revision_ts=None,
                    data=data,
                    provenance={
                        "source": "eia_steo",
                        "method": "archive_excel_base_workbook",
                        "scraper_version": SCRAPER_VERSION,
                        "publisher_url": ARCHIVE_INDEX_URL,
                        "workbook_url": url,
                        "issue_label": issue.issue_label,
                        "release_date": issue.release_date.isoformat(),
                        "selected_sheets": sorted(SERIES_BY_SHEET),
                        "selected_series_by_sheet": {
                            sheet: sorted(codes) for sheet, codes in SERIES_BY_SHEET.items()
                        },
                    },
                    vintage_quality=VintageQuality.TRUE_FIRST_RELEASE.value,
                    observation_start=data["observation_month"].min(),
                    observation_end=data["observation_month"].max(),
                )
            )
        return results

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
