"""CFTC Commitments of Traders ingester and WTI feature normalizer.

Release cadence: Friday >=15:30 ET (calendar: cftc_cot.yaml).
Observation semantics: positions as of Tuesday prior.

Network implementation: see CFTCCOTIngester.fetch.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from v2.ingest._http import HTTPClient
from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.writer import PITWriter

WTI_CFTC_CONTRACT_MARKET_CODE = "067651"
_NY = ZoneInfo("America/New_York")
SCRAPER_VERSION = "v2.b2b.0"

CFTC_HISTORY_ZIP_URL = (
    "https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip"
)
CFTC_CURRENT_YEAR_CSV_URL = "https://www.cftc.gov/files/dea/newcot/c_year.txt"


def _build_cftc_url(year: int, current_year: int) -> str:
    """Pick the per-year CFTC source URL.

    The historical compressed annual files cover prior years; for the
    current calendar year the publisher exposes ``c_year.txt`` (plain CSV).
    """
    if year >= current_year:
        return CFTC_CURRENT_YEAR_CSV_URL
    return CFTC_HISTORY_ZIP_URL.format(year=year)


class CFTCCOTIngester(BaseIngester):
    name = "cftc_cot"
    source = "cftc_cot"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        market_code: str = WTI_CFTC_CONTRACT_MARKET_CODE,
        years: list[int] | None = None,
        http: HTTPClient | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        self._market_code = market_code
        if years is None:
            years = [datetime.now(UTC).year]
        self._years = list(years)
        self._http = http if http is not None else HTTPClient()
        self._owns_http = http is None
        # Failure-isolation: after a fetch() call, year-level fetch errors
        # (e.g. 404 for a year not yet published) accumulate here so that
        # the scheduler can ingest the years that did succeed.
        self.last_run_failed_years: list[int] = []

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        self.last_run_failed_years = []
        current_year = (as_of_ts or datetime.now(UTC)).year
        out: list[FetchResult] = []
        for year in self._years:
            try:
                fr = self._fetch_year(year, current_year)
            except _YearFetchError as exc:
                self.last_run_failed_years.append(year)
                # Soft-fail: skip this year, continue with remaining.
                _ = exc
                continue
            if fr is not None:
                out.append(fr)
        return out

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # -- internals ------------------------------------------------------------

    def _fetch_year(self, year: int, current_year: int) -> FetchResult | None:
        url = _build_cftc_url(year, current_year)
        resp = self._http.get(url)
        if resp.status_code == 404:
            raise _YearFetchError(f"CFTC year {year} not found at {url}")
        if resp.status_code >= 400:
            raise _YearFetchError(
                f"CFTC year {year} GET {url} returned {resp.status_code}"
            )

        raw_df = _parse_cftc_payload(resp.content, url)
        # Pre-filter to the contract code; the existing transformer also
        # filters but doing it here keeps the raw-bytes path tight and
        # lets us produce useful diagnostics on empty filters.
        code_col = _resolve_code_col(raw_df)
        mask = (
            raw_df[code_col].astype(str).str.strip().str.strip("'\"")
            == self._market_code
        )
        filtered = raw_df[mask].copy()
        if filtered.empty:
            raise _YearFetchError(
                f"CFTC year {year}: no rows for market_code {self._market_code}"
            )

        # Hand off to the canonical transformer (untouched).
        features = normalize_wti_disaggregated_cot(
            filtered, market_code=self._market_code
        )
        # `features` is indexed by release_ts (UTC). We persist the table
        # keyed by report_date with the publication ts in the index.
        data = features.reset_index()

        # release_ts for the manifest row = latest publication ts in batch.
        release_ts = data["release_ts"].max().to_pydatetime()
        # observation window from the report_date column.
        report_dates = pd.to_datetime(data["report_date"]).dt.date
        observation_start: date = report_dates.min()
        observation_end: date = report_dates.max()

        provenance: dict[str, Any] = {
            "source": "cftc_cot",
            "method": "csv_download",
            "scraper_version": SCRAPER_VERSION,
            "market_code": self._market_code,
            "year": year,
            "endpoint": url,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
        }

        return FetchResult(
            source="cftc_cot",
            series=f"{self._market_code}_disaggregated",
            release_ts=release_ts,
            revision_ts=None,
            data=data,
            provenance=provenance,
            observation_start=observation_start,
            observation_end=observation_end,
        )


class _YearFetchError(Exception):
    """Internal, soft-failure marker for per-year fetch errors."""


_CODE_COL_DTYPES = {
    "CFTC_Contract_Market_Code": str,
    "CFTC_Contract_Market_Code_Quotes": str,
}


def _parse_cftc_payload(content: bytes, url: str) -> pd.DataFrame:
    """Decode either the zipped annual archive or the plain CSV stream.

    Force the contract-code column to string dtype so leading zeros (e.g.
    "067651") survive ``pd.read_csv``'s integer auto-coercion.
    """
    if url.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            members = [
                n for n in zf.namelist() if n.lower().endswith((".txt", ".csv"))
            ]
            if not members:
                raise _YearFetchError(f"CFTC zip {url}: no .txt/.csv members")
            with zf.open(members[0]) as fh:
                return pd.read_csv(fh, dtype=_CODE_COL_DTYPES)
    return pd.read_csv(io.BytesIO(content), dtype=_CODE_COL_DTYPES)


def _resolve_code_col(frame: pd.DataFrame) -> str:
    for name in ("CFTC_Contract_Market_Code", "CFTC_Contract_Market_Code_Quotes"):
        if name in frame.columns:
            return name
    raise _YearFetchError(
        "CFTC payload missing CFTC_Contract_Market_Code column"
    )


def normalize_wti_disaggregated_cot(
    data: pd.DataFrame | Path,
    *,
    market_code: str = WTI_CFTC_CONTRACT_MARKET_CODE,
) -> pd.DataFrame:
    """Return PIT-eligible WTI COT features indexed by release timestamp.

    The input is the CFTC disaggregated futures-only historical text/CSV shape.
    The output index is Friday 15:30 America/New_York converted to UTC, not the
    Tuesday report date. This makes the frame safe for backward-as-of merging
    into decision rows.
    """
    frame = pd.read_csv(data) if isinstance(data, Path) else data.copy()
    code_col = _first_present(
        frame,
        "CFTC_Contract_Market_Code",
        "CFTC_Contract_Market_Code_Quotes",
    )
    date_col = _first_present(
        frame,
        "As_of_Date_Form_MM/DD/YYYY",
        "Report_Date_as_MM_DD_YYYY",
    )
    required = [
        code_col,
        date_col,
        "Open_Interest_All",
        "Prod_Merc_Positions_Long_All",
        "Prod_Merc_Positions_Short_All",
        "Swap_Positions_Long_All",
        "Swap__Positions_Short_All",
        "M_Money_Positions_Long_All",
        "M_Money_Positions_Short_All",
        "Other_Rept_Positions_Long_All",
        "Other_Rept_Positions_Short_All",
        "NonRept_Positions_Long_All",
        "NonRept_Positions_Short_All",
    ]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError("CFTC COT frame missing columns: " + ", ".join(missing))

    filtered = frame[
        frame[code_col].astype(str).str.strip().str.strip("'\"") == market_code
    ].copy()
    if filtered.empty:
        raise ValueError(f"no CFTC COT rows for market code {market_code}")

    report_date = pd.to_datetime(filtered[date_col], errors="coerce")
    if report_date.isna().any():
        raise ValueError("CFTC COT report date parse failed")

    numeric_cols = [name for name in required if name not in {code_col, date_col}]
    for col in numeric_cols:
        filtered[col] = _numeric(filtered[col])

    output = pd.DataFrame(index=filtered.index)
    output["report_date"] = report_date.dt.date
    output["open_interest"] = filtered["Open_Interest_All"]
    output["prod_merc_net"] = (
        filtered["Prod_Merc_Positions_Long_All"]
        - filtered["Prod_Merc_Positions_Short_All"]
    )
    output["swap_net"] = (
        filtered["Swap_Positions_Long_All"]
        - filtered["Swap__Positions_Short_All"]
    )
    output["managed_money_net"] = (
        filtered["M_Money_Positions_Long_All"]
        - filtered["M_Money_Positions_Short_All"]
    )
    output["other_reportable_net"] = (
        filtered["Other_Rept_Positions_Long_All"]
        - filtered["Other_Rept_Positions_Short_All"]
    )
    output["nonreportable_net"] = (
        filtered["NonRept_Positions_Long_All"]
        - filtered["NonRept_Positions_Short_All"]
    )
    for col in [
        "prod_merc_net",
        "swap_net",
        "managed_money_net",
        "other_reportable_net",
        "nonreportable_net",
    ]:
        output[f"{col}_oi"] = output[col] / output["open_interest"].replace(0, pd.NA)

    release_ts = [
        _cot_release_ts(pd.Timestamp(item).to_pydatetime())
        for item in report_date
    ]
    output.index = pd.DatetimeIndex(release_ts, name="release_ts")
    output = output.sort_index()
    output = output[~output.index.duplicated(keep="last")]
    return output


def _cot_release_ts(report_date: datetime) -> datetime:
    report_day = report_date.date()
    days_until_friday = (4 - report_day.weekday()) % 7
    release_day = report_day + timedelta(days=days_until_friday)
    local = datetime.combine(release_day, time(15, 30), tzinfo=_NY)
    return local.astimezone(UTC)


def _numeric(values: pd.Series) -> pd.Series:
    return pd.to_numeric(
        values.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


def _first_present(frame: pd.DataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise ValueError("CFTC COT frame missing one of: " + ", ".join(names))
