"""WTI front-month futures price ingester (stooq primary, Yahoo fallback).

Release cadence: daily after CME EOD (~14:30 ET for settlement).
Series: ``CL_FRONT_DAILY_EOD`` — daily OHLCV for the WTI front-month
continuous symbol (CL.F on stooq, CL=F on Yahoo Finance).

Both sources are free and redistribute CME EOD settlement with typical
<24h lag. Intraday rows are inadmissible: a row whose ``observation_date``
column carries an HH:MM:SS suffix raises ``IntradayPayloadError``. Rows
dated today or in the future are dropped (defensive trim).
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime, time, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from v2.ingest._http import HTTPClient, RetryExhaustedError
from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.writer import PITWriter

SCRAPER_VERSION = "v2.b2b.0"
_NY = ZoneInfo("America/New_York")

STOOQ_URL = "https://stooq.com/q/d/l/?s=cl.f&i=d"
YAHOO_URL = "https://query1.finance.yahoo.com/v7/finance/download/CL=F"


class IntradayPayloadError(Exception):
    """Raised when the daily WTI feed contains intraday timestamps.

    Daily ingester refuses to emit a FetchResult mixing settlement and
    intraday bars; the caller must retry against an EOD-only payload.
    """


class WTIPricesIngester(BaseIngester):
    name = "wti_prices"
    source = "wti_prices"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        http: HTTPClient | None = None,
        source_priority: list[str] | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        self._http = http if http is not None else HTTPClient()
        self._owns_http = http is None
        if source_priority is None:
            source_priority = ["stooq", "yahoo"]
        self._source_priority = list(source_priority)

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        now_utc = as_of_ts or datetime.now(UTC)
        last_exc: Exception | None = None
        for src in self._source_priority:
            try:
                return [self._fetch_source(src, now_utc)]
            except RetryExhaustedError as exc:
                last_exc = exc
                continue
            except _EmptyBodyError as exc:
                last_exc = exc
                continue
        raise RuntimeError(
            f"all WTI price sources failed: {self._source_priority!r}; "
            f"last error: {last_exc!r}"
        )

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # -- internals ------------------------------------------------------------

    def _fetch_source(self, src: str, now_utc: datetime) -> FetchResult:
        if src == "stooq":
            return self._fetch_stooq(now_utc)
        if src == "yahoo":
            return self._fetch_yahoo(now_utc)
        raise ValueError(f"unknown WTI source {src!r}")

    def _fetch_stooq(self, now_utc: datetime) -> FetchResult:
        resp = self._http.get(STOOQ_URL)
        if not resp.content or not resp.content.strip():
            raise _EmptyBodyError("stooq returned empty body")
        df = _parse_csv(resp.content)
        df = _normalize_ohlcv(df, today_utc=now_utc)
        if df.empty:
            raise _EmptyBodyError("stooq CSV had no admissible rows")

        release_ts = _release_ts_from_last_modified(
            resp.last_modified, now_utc
        )
        provenance: dict[str, Any] = {
            "source": "wti_prices",
            "method": "csv_download",
            "scraper_version": SCRAPER_VERSION,
            "data_source": "stooq",
            "endpoint": STOOQ_URL,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
        }
        return FetchResult(
            source="wti_prices",
            series="CL_FRONT_DAILY_EOD",
            release_ts=release_ts,
            revision_ts=None,
            data=df,
            provenance=provenance,
            observation_start=df["observation_date"].min(),
            observation_end=df["observation_date"].max(),
        )

    def _fetch_yahoo(self, now_utc: datetime) -> FetchResult:
        # Default: pull a comfortable window. Operators can subclass and
        # override this method if they want a narrower or wider span.
        period_end = int(now_utc.timestamp())
        period_start = int((now_utc - timedelta(days=365 * 5)).timestamp())
        resp = self._http.get(
            YAHOO_URL,
            params={
                "period1": str(period_start),
                "period2": str(period_end),
                "interval": "1d",
            },
        )
        if not resp.content or not resp.content.strip():
            raise _EmptyBodyError("yahoo returned empty body")
        df = _parse_csv(resp.content)
        df = _normalize_ohlcv(df, today_utc=now_utc)
        if df.empty:
            raise _EmptyBodyError("yahoo CSV had no admissible rows")

        release_ts = _release_ts_from_last_modified(
            resp.last_modified, now_utc
        )
        provenance: dict[str, Any] = {
            "source": "wti_prices",
            "method": "csv_download",
            "scraper_version": SCRAPER_VERSION,
            "data_source": "yahoo",
            "endpoint": YAHOO_URL,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
        }
        return FetchResult(
            source="wti_prices",
            series="CL_FRONT_DAILY_EOD",
            release_ts=release_ts,
            revision_ts=None,
            data=df,
            provenance=provenance,
            observation_start=df["observation_date"].min(),
            observation_end=df["observation_date"].max(),
        )


class _EmptyBodyError(Exception):
    """Internal: source returned no parseable rows; fall through to next."""


def _parse_csv(content: bytes) -> pd.DataFrame:
    # Both stooq and yahoo emit CSV with header rows; normalise column
    # names to lower_snake before any further checks.
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]
    return df


def _normalize_ohlcv(df: pd.DataFrame, *, today_utc: datetime) -> pd.DataFrame:
    """Coerce a parsed CSV to ``[observation_date, open, high, low, close, volume]``.

    Hard rules:
        - HH:MM:SS in any ``date`` cell is intraday: raise.
        - Rows dated today or in the future are dropped (defensive trim).
    """
    if "date" not in df.columns:
        raise ValueError("WTI CSV missing 'date' column")
    date_strings = df["date"].astype(str).str.strip()

    # Intraday detection: stooq daily payloads carry pure YYYY-MM-DD; any
    # whitespace-followed time component (e.g. '2026-04-25 14:30:00')
    # signals an intraday tick that we must refuse.
    has_intraday = date_strings.str.contains(r"\s\d{1,2}:", regex=True, na=False)
    if has_intraday.any():
        raise IntradayPayloadError(
            "WTI CSV contains intraday HH:MM:SS timestamps; daily-only "
            "ingester refuses to mix settlement and intraday bars."
        )

    parsed = pd.to_datetime(date_strings, errors="coerce")
    df = df.assign(observation_date=parsed.dt.date)
    df = df.dropna(subset=["observation_date"])

    today_local = today_utc.astimezone(_NY).date()
    before_today = df["observation_date"].apply(lambda d: d < today_local)
    df = df[before_today].copy()

    columns = ["observation_date", "open", "high", "low", "close", "volume"]
    for col in columns:
        if col not in df.columns:
            df[col] = pd.NA
    out = df[columns].reset_index(drop=True)
    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    return out


def _release_ts_from_last_modified(
    last_modified: str | None, now_utc: datetime
) -> datetime:
    """Resolve the publisher release timestamp.

    Prefer the HTTP ``Last-Modified`` header where present (stooq exposes
    it). When absent (Yahoo doesn't always set it on these CSV exports),
    fall back to "yesterday 14:30 ET" — the CME settlement time for the
    last admissible bar.
    """
    if last_modified:
        try:
            parsed = parsedate_to_datetime(last_modified)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (TypeError, ValueError):
            pass
    yesterday: date = (now_utc.astimezone(_NY).date() - timedelta(days=1))
    local = datetime.combine(yesterday, time(14, 30), tzinfo=_NY)
    return local.astimezone(UTC)
