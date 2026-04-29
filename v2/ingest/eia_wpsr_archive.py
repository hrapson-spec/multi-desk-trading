"""First-release EIA WPSR archive ingester.

This ingester restores historical Weekly Petroleum Status Report issue
tables from EIA's public archive. It intentionally does not use the EIA
series API, because that API returns current revised history rather than
the table values available at each historical release timestamp.
"""

from __future__ import annotations

import csv
import html
import io
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import pandas as pd

from v2.ingest._http import HTTPClient
from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.quality import VintageQuality
from v2.pit_store.writer import PITWriter

ARCHIVE_INDEX_URL = "https://www.eia.gov/petroleum/supply/weekly/archive/"
SCRAPER_VERSION = "v2.wpsr_archive.0"
LATENCY_GUARD_MINUTES = 5
NY = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class WPSRSeriesMapping:
    series_id: str
    table_id: str
    label: str
    units: str
    value_scale: float = 1.0
    section: str | None = None


SERIES_MAPPINGS: tuple[WPSRSeriesMapping, ...] = (
    WPSRSeriesMapping("WCESTUS1", "table4", "Commercial (Excluding SPR)", "kbbl", 1000.0),
    WPSRSeriesMapping("WCSSTUS1", "table4", "SPR", "kbbl", 1000.0),
    WPSRSeriesMapping("W_EPC0_SAX_YCUOK_MBBL", "table4", "Cushing", "kbbl", 1000.0),
    WPSRSeriesMapping("WGTSTUS1", "table4", "Total Motor Gasoline", "kbbl", 1000.0),
    WPSRSeriesMapping("WDISTUS1", "table4", "Distillate Fuel Oil", "kbbl", 1000.0),
    WPSRSeriesMapping("WKJSTUS1", "table4", "Kerosene-Type Jet Fuel", "kbbl", 1000.0),
    WPSRSeriesMapping("WPRSTUS1", "table4", "Propane/Propylene", "kbbl", 1000.0),
    WPSRSeriesMapping(
        "WCRFPUS2",
        "table1",
        "Domestic Production",
        "kbbl/d",
        section="Crude Oil Supply",
    ),
    WPSRSeriesMapping(
        "WCRIMUS2",
        "table1",
        "Imports",
        "kbbl/d",
        section="Crude Oil Supply",
    ),
    WPSRSeriesMapping(
        "WCREXUS2",
        "table1",
        "Exports",
        "kbbl/d",
        section="Crude Oil Supply",
    ),
    WPSRSeriesMapping(
        "WRPUPUS2",
        "table1",
        "Total",
        "kbbl/d",
        section="Products Supplied",
    ),
    WPSRSeriesMapping(
        "WPULEUS3",
        "table2",
        "Percent Utilization",
        "percent",
        section="Refiner Inputs and Utilization",
    ),
)


@dataclass(frozen=True)
class WPSRIssue:
    issue_url: str
    release_date: date
    week_ending: date
    release_ts: datetime
    usable_after_ts: datetime
    csv_links: dict[str, str]


class EIAWPSRArchiveIngester(BaseIngester):
    """Restore first-release WPSR table vintages from EIA archive pages."""

    name = "eia_wpsr_archive"
    source = "eia"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        since: date | None = None,
        until: date | None = None,
        issue_urls: list[str] | None = None,
        series_ids: list[str] | None = None,
        http: HTTPClient | None = None,
        archive_index_url: str = ARCHIVE_INDEX_URL,
    ) -> None:
        super().__init__(writer, manifest)
        self._since = since
        self._until = until
        self._issue_urls = list(issue_urls) if issue_urls is not None else None
        self._series_ids = set(series_ids) if series_ids is not None else None
        self._archive_index_url = archive_index_url
        self._http_owned = http is None
        self._http = http if http is not None else HTTPClient()
        self.last_run_failed_issues: list[tuple[str, str]] = []
        self.last_run_failed_series: list[tuple[str, str]] = []

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        del as_of_ts
        results: list[FetchResult] = []
        for issue_url in self._issue_urls_to_fetch():
            issue = self._fetch_issue(issue_url)
            if issue is None:
                continue
            if self._since is not None and issue.release_date < self._since:
                continue
            if self._until is not None and issue.release_date > self._until:
                continue
            tables = self._fetch_required_tables(issue)
            results.extend(self._results_for_issue(issue, tables))
        return results

    def _issue_urls_to_fetch(self) -> list[str]:
        if self._issue_urls is not None:
            return self._issue_urls
        resp = self._http.get(self._archive_index_url)
        if resp.status_code != 200:
            raise RuntimeError(
                f"EIA WPSR archive index returned HTTP {resp.status_code}: "
                f"{self._archive_index_url}"
            )
        urls = parse_archive_issue_links(
            resp.content.decode("utf-8", errors="replace"),
            base_url=self._archive_index_url,
        )
        return [
            u
            for u in urls
            if _url_date_in_bounds(u, since=self._since, until=self._until)
        ]

    def _fetch_issue(self, issue_url: str) -> WPSRIssue | None:
        try:
            resp = self._http.get(issue_url)
        except Exception as exc:  # noqa: BLE001
            self.last_run_failed_issues.append((issue_url, f"http_error: {exc}"))
            return None
        if resp.status_code != 200:
            self.last_run_failed_issues.append(
                (issue_url, f"http_status_{resp.status_code}")
            )
            return None
        try:
            html_text = resp.content.decode("utf-8", errors="replace")
            release_date, week_ending = parse_issue_dates(html_text)
        except ValueError as exc:
            self.last_run_failed_issues.append((issue_url, f"metadata_error: {exc}"))
            return None
        release_ts = _release_datetime_utc(release_date)
        return WPSRIssue(
            issue_url=issue_url,
            release_date=release_date,
            week_ending=week_ending,
            release_ts=release_ts,
            usable_after_ts=release_ts + timedelta(minutes=LATENCY_GUARD_MINUTES),
            csv_links=parse_issue_csv_links(html_text, base_url=issue_url),
        )

    def _fetch_required_tables(self, issue: WPSRIssue) -> dict[str, pd.DataFrame]:
        tables: dict[str, pd.DataFrame] = {}
        required_table_ids = {
            m.table_id
            for m in SERIES_MAPPINGS
            if self._series_ids is None or m.series_id in self._series_ids
        }
        for table_id in sorted(required_table_ids):
            url = issue.csv_links.get(table_id)
            if url is None:
                self.last_run_failed_issues.append(
                    (issue.issue_url, f"missing_csv_link:{table_id}")
                )
                continue
            try:
                resp = self._http.get(url)
            except Exception as exc:  # noqa: BLE001
                self.last_run_failed_issues.append((url, f"http_error: {exc}"))
                continue
            if resp.status_code != 200:
                self.last_run_failed_issues.append(
                    (url, f"http_status_{resp.status_code}")
                )
                continue
            tables[table_id] = read_wpsr_csv(resp.content)
        return tables

    def _results_for_issue(
        self, issue: WPSRIssue, tables: dict[str, pd.DataFrame]
    ) -> list[FetchResult]:
        results: list[FetchResult] = []
        for mapping in SERIES_MAPPINGS:
            if self._series_ids is not None and mapping.series_id not in self._series_ids:
                continue
            table = tables.get(mapping.table_id)
            if table is None:
                continue
            try:
                raw_value = extract_mapping_value(table, mapping)
            except LookupError as exc:
                self.last_run_failed_series.append((mapping.series_id, str(exc)))
                continue
            df = pd.DataFrame(
                {
                    "period": [issue.week_ending.isoformat()],
                    "value": [raw_value * mapping.value_scale],
                    "units": [mapping.units],
                    "frequency": ["weekly"],
                    "table_id": [mapping.table_id],
                    "row_label": [mapping.label],
                    "issue_url": [issue.issue_url],
                }
            )
            results.append(
                FetchResult(
                    source=self.source,
                    dataset="wpsr",
                    series=mapping.series_id,
                    release_ts=issue.release_ts,
                    usable_after_ts=issue.usable_after_ts,
                    revision_ts=None,
                    data=df,
                    provenance={
                        "source": "eia",
                        "method": "wpsr_archive_csv",
                        "scraper_version": SCRAPER_VERSION,
                        "series_id": mapping.series_id,
                        "table_id": mapping.table_id,
                        "issue_url": issue.issue_url,
                        "release_date": issue.release_date.isoformat(),
                        "week_ending": issue.week_ending.isoformat(),
                    },
                    vintage_quality=VintageQuality.TRUE_FIRST_RELEASE.value,
                    observation_start=issue.week_ending,
                    observation_end=issue.week_ending,
                )
            )
        return results


def parse_archive_issue_links(html_text: str, *, base_url: str) -> list[str]:
    """Return de-duplicated absolute WPSR issue URLs from the archive index."""
    links: set[str] = set()
    pattern = r"""href=["']([^"']*wpsr_\d{4}_\d{2}_\d{2}(?:_data)?\.php)["']"""
    for href in re.findall(pattern, html_text):
        links.add(urljoin(base_url, html.unescape(href)))
    return sorted(links)


def parse_issue_csv_links(html_text: str, *, base_url: str) -> dict[str, str]:
    links: dict[str, str] = {}
    pattern = r"""href=["']([^"']*csv/(table[0-9a-z]+)\.csv)["']"""
    for href, table_id in re.findall(pattern, html_text, flags=re.IGNORECASE):
        links[table_id.lower()] = urljoin(base_url, html.unescape(href))
    return links


def parse_issue_dates(html_text: str) -> tuple[date, date]:
    clean = _plain_text(html_text)
    week = re.search(r"Data for week ending\s+([A-Za-z]+ \d{1,2}, \d{4})", clean)
    release = re.search(r"Release Date:\s+([A-Za-z]+ \d{1,2}, \d{4})", clean)
    if week is None or release is None:
        raise ValueError("could not parse WPSR week-ending and release dates")
    return _parse_us_date(release.group(1)), _parse_us_date(week.group(1))


def read_wpsr_csv(content: bytes) -> pd.DataFrame:
    text = content.decode("utf-8-sig", errors="replace").replace("\x1a", "")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return pd.DataFrame()
    width = max(len(row) for row in rows)
    padded = [row + [""] * (width - len(row)) for row in rows]
    return pd.DataFrame(padded, dtype=str)


def extract_mapping_value(table: pd.DataFrame, mapping: WPSRSeriesMapping) -> float:
    header_idx = _header_row_index(table, mapping)
    value_col = _first_period_column(table.iloc[header_idx])
    for idx in range(header_idx + 1, len(table)):
        row = table.iloc[idx]
        if _is_header_row(row):
            break
        if _row_matches(row, mapping):
            return _parse_number(row.iloc[value_col])
    raise LookupError(
        f"{mapping.series_id}: row not found in {mapping.table_id}: "
        f"section={mapping.section!r}, label={mapping.label!r}"
    )


def _header_row_index(table: pd.DataFrame, mapping: WPSRSeriesMapping) -> int:
    for idx in range(len(table)):
        row = table.iloc[idx]
        if _is_header_row(row):
            if mapping.section is None and _normalize(str(row.iloc[0])) == "STUB_1":
                return idx
            if (
                mapping.section is not None
                and len(row) > 1
                and _normalize(str(row.iloc[0])) == "STUB_1"
                and _normalize(str(row.iloc[1])) == "STUB_2"
            ):
                return idx
    raise LookupError(f"header row not found for {mapping.table_id}")


def _first_period_column(row: pd.Series) -> int:
    for idx, value in enumerate(row):
        if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", str(value).strip()):
            return idx
    raise LookupError("no period column found in WPSR table header")


def _is_header_row(row: pd.Series) -> bool:
    return _normalize(str(row.iloc[0])) == "STUB_1"


def _row_matches(row: pd.Series, mapping: WPSRSeriesMapping) -> bool:
    if mapping.section is None:
        return _normalize(str(row.iloc[0])) == _normalize(mapping.label)
    if len(row) < 2:
        return False
    return (
        _normalize(str(row.iloc[0])) == _normalize(mapping.section)
        and _normalize(str(row.iloc[1])) == _normalize(mapping.label)
    )


def _parse_number(value: object) -> float:
    text = str(value).strip().replace(",", "")
    if text in {"", "� �", "--", "NA", "n/a"}:
        raise LookupError(f"non-numeric WPSR value: {value!r}")
    return float(text)


def _normalize(value: str) -> str:
    value = html.unescape(value).replace("\xa0", " ")
    value = re.sub(r"^\(\d+\)\s*", "", value.strip())
    value = re.sub(r"\s+", " ", value)
    return value


def _plain_text(html_text: str) -> str:
    text = html.unescape(html_text).replace("\xa0", " ")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def _parse_us_date(text: str) -> date:
    return datetime.strptime(text, "%B %d, %Y").date()


def _release_datetime_utc(issue_date: date) -> datetime:
    local = datetime.combine(issue_date, time(10, 30), tzinfo=NY)
    return local.astimezone(UTC)


def _url_date_in_bounds(
    url: str,
    *,
    since: date | None,
    until: date | None,
) -> bool:
    m = re.search(r"/(\d{4})_(\d{2})_(\d{2})(?:_data)?/", url)
    if m is None:
        return True
    url_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if since is not None and url_date < since:
        return False
    return not (until is not None and url_date > until)
