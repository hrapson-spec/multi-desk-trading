"""EIA Weekly Petroleum Status Report + petroleum supply ingester.

Release cadence: WPSR weekly Wednesday >=10:30 ET (calendar:
``v2/pit_store/calendars/eia_wpsr.yaml``); other EIA petroleum supply
series follow the same calendar.

This ingester pulls every EIA series flagged ``model_eligible: true``
in ``public_data_inventory.yaml``, including (but not limited to) the
WPSR core (``WCESTUS1``, ``WCSSTUS1``, ``W_EPC0_SAX_YCUOK_MBBL``) plus
production, imports, exports, refinery utilisation, and product stocks
/supplied series.

API: EIA API v2, base ``https://api.eia.gov/v2``. Each series is
fetched via ``GET /seriesid/{SERIES_ID}?api_key=...``. The response
``response.data`` array carries observations, ``response.metadata.updated``
carries the publisher release timestamp.

PIT discipline:
    * ``release_ts`` is the publisher timestamp from
      ``response.metadata.updated`` (parsed to UTC). Falls back to
      ``now(UTC)`` only when metadata is absent — recorded in provenance
      with ``release_ts_confidence: "low_fallback_now"``.
    * One :class:`v2.ingest.base.FetchResult` per series; ``revision_ts``
      is left as ``None`` so :meth:`PITWriter.write_vintage` auto-detects
      revisions via checksum.

Failure isolation:
    A single non-200 response does NOT abort the batch. Failed series
    IDs are recorded on ``self.last_run_failed_series`` (list of
    ``(series_id, reason)`` tuples). Series flagged
    ``verify_series_id_at_first_fetch`` in the registry may legitimately
    404 on first attempt.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import numpy as np
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
from v2.pit_store.quality import VintageQuality
from v2.pit_store.writer import PITWriter

EIA_API_V2_BASE = "https://api.eia.gov/v2"
SCRAPER_VERSION = "v2.b2b.0"


def _parse_iso_utc(s: str) -> datetime:
    """Parse an EIA ISO-ish timestamp into a UTC-aware datetime."""
    txt = s.strip()
    try:
        dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"unparseable EIA timestamp: {s!r}") from exc
    dt = dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    return dt


class EIAWPSRIngester(BaseIngester):
    """EIA petroleum-supply ingester (WPSR + non-WPSR series)."""

    name = "eia_wpsr"
    source = "eia"

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        series_ids: list[str] | None = None,
        http: HTTPClient | None = None,
        api_key: str | None = None,
        registry: PublicDataRegistry | None = None,
    ) -> None:
        super().__init__(writer, manifest)

        if registry is None:
            registry = load_registry()
        self._registry = registry

        if series_ids is None:
            eia_entries = entries_for_source(registry, "eia")
            series_ids = [
                e.series_id
                for e in eia_entries
                if e.model_eligible and e.series_id
            ]
        self._series_ids: list[str] = list(series_ids)

        # Defer API key resolution to fetch() so the ingester can be
        # instantiated and registered with the scheduler in environments
        # without a key (e.g. unit tests, dry-run audits).
        self._api_key_override = api_key

        self._http_owned = http is None
        self._http = http if http is not None else HTTPClient()

        self.last_run_failed_series: list[tuple[str, str]] = []

    # -------------------------------------------------------------------
    # internals
    # -------------------------------------------------------------------

    @property
    def _api_key(self) -> str:
        if self._api_key_override is not None:
            return self._api_key_override
        return get_api_key("eia")

    def _endpoint_for(self, series_id: str) -> str:
        return f"{EIA_API_V2_BASE}/seriesid/{series_id}"

    def _decode(self, body: bytes) -> Any:
        return json.loads(body.decode("utf-8"))

    def _build_dataframe(
        self,
        observations: list[dict[str, Any]],
        retrieved_at_utc: datetime,
    ) -> pd.DataFrame:
        """Coerce EIA observations into the canonical schema.

        Columns: ``[period, value, units, frequency, retrieved_at_utc]``.
        Null/None values become NaN (float64).
        """
        n = len(observations)
        if n == 0:
            return pd.DataFrame(
                {
                    "period": pd.Series([], dtype="object"),
                    "value": pd.Series([], dtype="float64"),
                    "units": pd.Series([], dtype="object"),
                    "frequency": pd.Series([], dtype="object"),
                    "retrieved_at_utc": pd.Series(
                        [], dtype="datetime64[ns, UTC]"
                    ),
                }
            )

        periods = [obs.get("period") for obs in observations]
        values: list[float] = []
        for obs in observations:
            v = obs.get("value")
            if v is None or v == "":
                values.append(float("nan"))
                continue
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                values.append(float("nan"))
        units = [obs.get("units") for obs in observations]
        frequency = [obs.get("frequency") for obs in observations]

        return pd.DataFrame(
            {
                "period": periods,
                "value": np.asarray(values, dtype="float64"),
                "units": units,
                "frequency": frequency,
                "retrieved_at_utc": pd.Series(
                    [retrieved_at_utc] * n,
                    dtype="datetime64[ns, UTC]",
                ),
            }
        )

    def _fetch_one(self, series_id: str) -> FetchResult | None:
        endpoint = self._endpoint_for(series_id)
        try:
            resp = self._http.get(
                endpoint,
                params={"api_key": self._api_key},
            )
        except Exception as exc:  # noqa: BLE001
            self.last_run_failed_series.append(
                (series_id, f"http_error: {type(exc).__name__}: {exc}")
            )
            return None

        if resp.status_code != 200:
            self.last_run_failed_series.append(
                (series_id, f"http_status_{resp.status_code}")
            )
            return None

        try:
            payload = self._decode(resp.content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self.last_run_failed_series.append(
                (series_id, f"decode_error: {exc}")
            )
            return None

        response_block: dict[str, Any] = (
            payload.get("response", {}) if isinstance(payload, dict) else {}
        )
        observations = response_block.get("data", []) or []
        metadata = response_block.get("metadata", {}) or {}
        updated_raw = metadata.get("updated")

        release_ts_confidence = "publisher_metadata"
        release_ts: datetime
        if updated_raw:
            try:
                release_ts = _parse_iso_utc(str(updated_raw))
            except ValueError:
                release_ts = datetime.now(UTC)
                release_ts_confidence = "low_fallback_now"
        else:
            release_ts = datetime.now(UTC)
            release_ts_confidence = "low_fallback_now"

        df = self._build_dataframe(observations, resp.retrieved_at_utc)
        if df.empty:
            self.last_run_failed_series.append((series_id, "empty_observations"))
            return None

        provenance: dict[str, Any] = {
            "source": "eia",
            "method": "api",
            "scraper_version": SCRAPER_VERSION,
            "series_id": series_id,
            "endpoint": endpoint,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
            "release_ts_confidence": release_ts_confidence,
        }

        return FetchResult(
            source=self.source,
            dataset="wpsr",
            series=series_id,
            release_ts=release_ts,
            revision_ts=None,
            data=df,
            provenance=provenance,
            vintage_quality=VintageQuality.LATEST_SNAPSHOT_NOT_PIT.value,
        )

    # -------------------------------------------------------------------
    # public API
    # -------------------------------------------------------------------

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        # Resolve API key up front; absence is a hard error, not a per-series
        # soft failure (MissingAPIKeyError must not be swallowed by failure
        # isolation in _fetch_one's broad-except).
        _ = self._api_key
        self.last_run_failed_series = []
        results: list[FetchResult] = []
        for series_id in self._series_ids:
            r = self._fetch_one(series_id)
            if r is not None:
                results.append(r)
        return results

    def close(self) -> None:
        if self._http_owned:
            self._http.close()
