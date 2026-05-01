"""Cboe VIX direct CSV ingester (resilience fallback only).

The canonical model-eligible VIX path is FRED ``VIXCLS`` — see the
``fred_vixcls`` registry entry. This module exists strictly as a
resilience fallback when FRED is unavailable, and the registered
``cboe_vix_direct`` entry has ``rights_status: display_only`` and
``model_eligible: false``. Default instantiation issues a typed warning
to make accidental promotion to the model path a loud failure.
"""

from __future__ import annotations

import io
import warnings
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import pandas as pd

from v2.ingest._http import HTTPClient
from v2.ingest.base import BaseIngester, FetchResult
from v2.pit_store.manifest import PITManifest
from v2.pit_store.writer import PITWriter

CBOE_VIX_HISTORY_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv"
)
SCRAPER_VERSION = "v2.b2b.0"


class CboeVIXNotPrimary(UserWarning):
    """Default Cboe-direct path is not the canonical model-eligible source.

    Canonical path is FRED VIXCLS. This warning fires when the ingester is
    instantiated without ``force_direct=True`` to make accidental use a
    loud failure rather than silent display-only data leaking into models.
    """


class CboeVIXIntradayRejectedError(ValueError):
    """Defense in depth: VIX_History.csv must be daily-only.

    Raised when an HH:MM:SS component is detected in the date column.
    """


class CboeVIXIngester(BaseIngester):
    name = "cboe_vix"
    source = "cboe_vix"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        force_direct: bool = False,
        http: HTTPClient | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        self._force_direct = force_direct
        if not force_direct:
            warnings.warn(
                "CboeVIXIngester instantiated without force_direct=True; the "
                "canonical model-eligible VIX path is FRED VIXCLS. The Cboe "
                "direct CSV is rights_status='display_only' and exists only "
                "as a resilience fallback. No HTTP fetch will be performed.",
                CboeVIXNotPrimary,
                stacklevel=2,
            )
            self._http: HTTPClient | None = None
            self._owns_http = False
        else:
            self._http = http if http is not None else HTTPClient()
            self._owns_http = http is None

    # -- public --------------------------------------------------------------

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        if not self._force_direct:
            # Default behaviour: no HTTP, no fetch. Caller already got a
            # CboeVIXNotPrimary warning at construction time.
            return []
        assert self._http is not None  # for type checkers
        resp = self._http.get(CBOE_VIX_HISTORY_URL)
        text = resp.content.decode("utf-8", errors="replace")
        df = pd.read_csv(io.StringIO(text))
        df = self._normalise_columns(df)

        # Defense in depth: refuse intraday rows.
        for d in df["observation_date"]:
            if isinstance(d, str) and (":" in d):
                raise CboeVIXIntradayRejectedError(
                    f"unexpected intraday timestamp in VIX_History.csv: {d!r}"
                )
        df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date

        release_ts = self._parse_last_modified(resp.last_modified)
        retrieved_at = resp.retrieved_at_utc

        observation_start = df["observation_date"].min() if len(df) else None
        observation_end = df["observation_date"].max() if len(df) else None

        provenance: dict[str, Any] = {
            "source": "cboe_vix",
            "method": "csv_download",
            "scraper_version": SCRAPER_VERSION,
            "endpoint": CBOE_VIX_HISTORY_URL,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
            "retrieved_at_utc": retrieved_at.isoformat(),
        }

        return [
            FetchResult(
                source="cboe_vix",
                series="VIXCLS_cboe_direct",
                release_ts=release_ts,
                revision_ts=None,
                data=df,
                provenance=provenance,
                observation_start=observation_start,
                observation_end=observation_end,
            )
        ]

    def close(self) -> None:
        if self._owns_http and self._http is not None:
            self._http.close()

    # -- internals -----------------------------------------------------------

    @staticmethod
    def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
        # Cboe VIX_History.csv canonical columns: DATE,OPEN,HIGH,LOW,CLOSE.
        # Tolerate case variations.
        col_map: dict[str, str] = {}
        for c in df.columns:
            lc = c.strip().lower()
            if lc == "date":
                col_map[c] = "observation_date"
            elif lc in {"open", "high", "low", "close"}:
                col_map[c] = lc.upper()
        df = df.rename(columns=col_map)
        required = {"observation_date", "OPEN", "HIGH", "LOW", "CLOSE"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(
                f"VIX_History.csv missing expected columns: {sorted(missing)}"
            )
        return df[["observation_date", "OPEN", "HIGH", "LOW", "CLOSE"]]

    @staticmethod
    def _parse_last_modified(last_modified: str | None) -> datetime:
        if not last_modified:
            return datetime.now(UTC)
        try:
            dt = parsedate_to_datetime(last_modified)
        except (TypeError, ValueError):
            return datetime.now(UTC)
        if dt is None:
            return datetime.now(UTC)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)


__all__ = [
    "CBOE_VIX_HISTORY_URL",
    "CboeVIXIngester",
    "CboeVIXIntradayRejectedError",
    "CboeVIXNotPrimary",
]
