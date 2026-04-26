"""FRED/ALFRED (Archival FRED) vintage-aware macro ingester.

Release cadence: irregular, series-specific (calendar: fred_alfred.yaml).
Unlike the other three ingesters, ALFRED exposes real-time periods and
vintage_date explicitly; a single network round-trip can return many
vintages for one series.

Network implementation: FRED REST API. Endpoints used:

    GET https://api.stlouisfed.org/fred/series
        ?series_id=<id>&api_key=<key>&file_type=json
    GET https://api.stlouisfed.org/fred/series/observations
        ?series_id=<id>&api_key=<key>&file_type=json
        [&observation_start=YYYY-MM-DD]
        [&realtime_start=YYYY-MM-DD&realtime_end=YYYY-MM-DD]

Operator action required before promotion:
    1. Register at https://research.stlouisfed.org/docs/api/api_key.html
       (free). Store key in ~/.config/v2/operator.yaml as `fred_api_key`.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from v2.ingest._http import HTTPClient
from v2.ingest._secrets import get_api_key
from v2.ingest.base import BaseIngester, FetchResult
from v2.ingest.public_data_registry import (
    PublicDataRegistry,
    entries_for_source,
    load_registry,
)
from v2.pit_store.manifest import PITManifest
from v2.pit_store.writer import PITWriter

FRED_API_BASE = "https://api.stlouisfed.org/fred"
SCRAPER_VERSION = "v2.b2b.0"


def _parse_fred_last_updated(s: str) -> datetime:
    """Parse FRED's ``last_updated`` ISO-ish timestamp into a UTC datetime.

    FRED returns formats like ``"2026-04-23 09:08:01-05"``. The trailing
    offset is hours-only (no colon, no minutes). We normalise to a form
    Python's ``datetime.fromisoformat`` accepts in 3.11+ ("YYYY-MM-DD HH:MM:SS+HH:MM")
    and convert to UTC.
    """
    s = s.strip()
    # Match a tz suffix like ``-05`` or ``+10`` or ``-0500``.
    m = re.search(r"([+-])(\d{2})(\d{2})?$", s)
    if m is None:
        # No timezone; assume UTC.
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    sign, hours, minutes = m.group(1), m.group(2), m.group(3) or "00"
    head = s[: m.start()]
    iso = f"{head}{sign}{hours}:{minutes}"
    dt = datetime.fromisoformat(iso)
    return dt.astimezone(UTC)


class FREDAlfredIngester(BaseIngester):
    name = "fred_alfred"
    source = "fred"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        series_ids: list[str] | None = None,
        http: HTTPClient | None = None,
        api_key: str | None = None,
        registry: PublicDataRegistry | None = None,
        realtime_start: date | None = None,
        realtime_end: date | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        # Defer API key resolution to fetch() so the ingester can be
        # instantiated without a key (scheduler registration, dry-run audits).
        self._api_key_override = api_key
        self._http = http if http is not None else HTTPClient()
        self._owns_http = http is None
        self._registry = registry
        self._realtime_start = realtime_start
        self._realtime_end = realtime_end
        if series_ids is None:
            reg = registry if registry is not None else load_registry()
            entries = entries_for_source(reg, "fred")
            series_ids = [
                e.series_id for e in entries if e.model_eligible and e.series_id is not None
            ]
        self._series_ids: list[str] = list(series_ids)
        self._history_starts: dict[str, date | None] = {}
        if registry is not None or series_ids is None:
            reg = registry if registry is not None else load_registry()
            for e in entries_for_source(reg, "fred"):
                if e.series_id is not None:
                    self._history_starts[e.series_id] = e.history_start

    # -- public --------------------------------------------------------------

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        out: list[FetchResult] = []
        for sid in self._series_ids:
            out.append(self._fetch_series(sid))
        return out

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    # -- internals -----------------------------------------------------------

    @property
    def _api_key(self) -> str:
        if self._api_key_override is not None:
            return self._api_key_override
        return get_api_key("fred")

    def _fetch_series(self, series_id: str) -> FetchResult:
        # 1) /series — metadata for release_ts via last_updated.
        meta_endpoint = f"{FRED_API_BASE}/series"
        meta_params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        meta_resp = self._http.get(meta_endpoint, params=meta_params)
        meta_payload = json.loads(meta_resp.content.decode("utf-8"))
        try:
            series_info = meta_payload["seriess"][0]
        except (KeyError, IndexError) as exc:
            raise ValueError(
                f"FRED /series response missing 'seriess[0]' for {series_id!r}"
            ) from exc
        last_updated = series_info.get("last_updated")
        if not last_updated:
            raise ValueError(
                f"FRED /series response for {series_id!r} missing 'last_updated'"
            )
        release_ts = _parse_fred_last_updated(last_updated)
        units = series_info.get("units", "")
        frequency = series_info.get("frequency_short", series_info.get("frequency", ""))

        # 2) /series/observations — values.
        obs_endpoint = f"{FRED_API_BASE}/series/observations"
        obs_params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
        }
        history_start = self._history_starts.get(series_id)
        if history_start is not None:
            obs_params["observation_start"] = history_start.isoformat()
        if self._realtime_start is not None:
            obs_params["realtime_start"] = self._realtime_start.isoformat()
        if self._realtime_end is not None:
            obs_params["realtime_end"] = self._realtime_end.isoformat()

        obs_resp = self._http.get(obs_endpoint, params=obs_params)
        obs_payload = json.loads(obs_resp.content.decode("utf-8"))
        observations = obs_payload.get("observations", [])
        if not observations:
            raise ValueError(
                f"FRED /series/observations returned no rows for {series_id!r}"
            )

        # retrieved_at_utc must be stable across identical re-fetches (so the
        # PIT writer's checksum-based idempotency holds). Use the publisher
        # release timestamp as the row-level "retrieved_at" — wall-clock
        # retrieval time is recorded in provenance, not in the row schema.
        retrieved_at = release_ts
        rows = []
        for obs in observations:
            obs_date_str = obs.get("date")
            if not obs_date_str:
                continue
            value_str = obs.get("value", ".")
            value = float("nan") if value_str == "." else float(value_str)
            rows.append(
                {
                    "observation_date": date.fromisoformat(obs_date_str),
                    "value": value,
                    "units": units,
                    "frequency": frequency,
                    "retrieved_at_utc": retrieved_at,
                }
            )

        df = pd.DataFrame(
            rows,
            columns=["observation_date", "value", "units", "frequency", "retrieved_at_utc"],
        )
        df["value"] = df["value"].astype(float)

        observation_start: date | None = (
            df["observation_date"].min() if len(df) else None
        )
        observation_end: date | None = (
            df["observation_date"].max() if len(df) else None
        )

        provenance: dict[str, Any] = {
            "source": "fred",
            "method": "api",
            "scraper_version": SCRAPER_VERSION,
            "series_id": series_id,
            "endpoint": obs_endpoint,
            "etag": obs_resp.etag,
            "last_modified": obs_resp.last_modified,
            "wall_clock_retrieved_at_utc": obs_resp.retrieved_at_utc.isoformat(),
        }
        if self._realtime_start is not None:
            provenance["realtime_start"] = self._realtime_start.isoformat()
        if self._realtime_end is not None:
            provenance["realtime_end"] = self._realtime_end.isoformat()

        return FetchResult(
            source="fred",
            series=series_id,
            release_ts=release_ts,
            revision_ts=None,
            data=df,
            provenance=provenance,
            observation_start=observation_start,
            observation_end=observation_end,
        )
