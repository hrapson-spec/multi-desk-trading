"""Multi-asset stooq EOD ingester (Tier 3.B).

Parameterised wrapper around the stooq EOD CSV path used by
``v2.ingest.wti_prices``. Supports the executable target streams
required by data-acquisition plan §D.10:

- Brent front-month: stooq symbol ``b.f``
- RBOB gasoline front-month: stooq symbol ``rb.f``
- Henry Hub natural gas front-month: stooq symbol ``ng.f``

Each instance writes to its own (source, dataset) namespace under
the PIT manifest, so per-target N counts remain segregated per
spec §11 forbidden #4.

Same license caveats as ``cl_front_eod_pit``: stooq redistribution
under free-source rehearsal only; not for real-capital execution
or evidence-grade replay. See
``data/s4_0/free_source/licence_clearance/owner_clearance_decision.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from v2.ingest._http import HTTPClient, RetryExhaustedError
from v2.ingest.base import BaseIngester, FetchResult
from v2.ingest.wti_prices import (
    _normalize_ohlcv,
    _parse_csv,
    _release_ts_from_last_modified,
)
from v2.pit_store.manifest import PITManifest
from v2.pit_store.quality import VintageQuality
from v2.pit_store.writer import PITWriter

SCRAPER_VERSION = "v2.stooq_multi_asset.0"
_NY = ZoneInfo("America/New_York")
STOOQ_BASE = "https://stooq.com/q/d/l/"


@dataclass(frozen=True)
class AssetSpec:
    """Per-asset configuration for the multi-asset ingester."""

    name: str  # 'brent' | 'rbob' | 'ng'
    stooq_symbol: str  # 'b.f' | 'rb.f' | 'ng.f'
    pit_source: str  # PIT-store source label
    pit_dataset: str
    pit_series: str
    target_variable: str  # contracts/target_variables.py constant value


ASSET_REGISTRY: dict[str, AssetSpec] = {
    "brent": AssetSpec(
        name="brent",
        stooq_symbol="b.f",
        pit_source="brent_front_eod_pit",
        pit_dataset="front_month_eod_pit_spine",
        pit_series="BRENT_FRONT_DAILY_EOD",
        target_variable="brent_front_5d_log_return",
    ),
    "rbob": AssetSpec(
        name="rbob",
        stooq_symbol="rb.f",
        pit_source="rbob_front_eod_pit",
        pit_dataset="front_month_eod_pit_spine",
        pit_series="RBOB_FRONT_DAILY_EOD",
        target_variable="rbob_front_5d_log_return",
    ),
    "ng": AssetSpec(
        name="ng",
        stooq_symbol="ng.f",
        pit_source="ng_front_eod_pit",
        pit_dataset="front_month_eod_pit_spine",
        pit_series="NG_FRONT_DAILY_EOD",
        target_variable="ng_front_5d_log_return",
    ),
}


class _EmptyBodyError(Exception):
    pass


class StooqMultiAssetIngester(BaseIngester):
    """Per-asset stooq EOD ingester. Instantiate one per asset."""

    name = "stooq_multi_asset"
    source = "multi_asset"  # overridden per-asset

    def __init__(
        self,
        writer: PITWriter,
        manifest: PITManifest,
        *,
        asset: str,
        http: HTTPClient | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> None:
        super().__init__(writer, manifest)
        if asset not in ASSET_REGISTRY:
            raise ValueError(
                f"unknown asset {asset!r}; known: {sorted(ASSET_REGISTRY)}"
            )
        self._spec = ASSET_REGISTRY[asset]
        self.source = self._spec.pit_source  # type: ignore[misc]
        self._http = http if http is not None else HTTPClient()
        self._owns_http = http is None
        self._since = since
        self._until = until

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        now_utc = as_of_ts or datetime.now(UTC)
        url = f"{STOOQ_BASE}?s={self._spec.stooq_symbol}&i=d"
        try:
            resp = self._http.get(url)
        except RetryExhaustedError as exc:
            raise RuntimeError(
                f"stooq fetch failed for {self._spec.name}: {exc!r}"
            ) from exc
        if not resp.content or not resp.content.strip():
            raise _EmptyBodyError(f"stooq returned empty for {self._spec.stooq_symbol}")
        df = _parse_csv(resp.content)
        df = _normalize_ohlcv(df, today_utc=now_utc)
        if df.empty:
            raise _EmptyBodyError(f"stooq CSV had no admissible rows for {self._spec.name}")

        if self._since is not None:
            df = df[df["observation_date"] >= self._since]
        if self._until is not None:
            df = df[df["observation_date"] <= self._until]
        if df.empty:
            return []

        release_ts = _release_ts_from_last_modified(resp.last_modified, now_utc)

        most_recent = df["observation_date"].max()
        days_lag = (now_utc.astimezone(_NY).date() - most_recent).days
        if days_lag <= 1:
            vq = VintageQuality.TRUE_FIRST_RELEASE.value
        else:
            vq = VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value

        provenance: dict[str, Any] = {
            "source": self._spec.pit_source,
            "method": "stooq_csv_download",
            "scraper_version": SCRAPER_VERSION,
            "data_source": "stooq",
            "stooq_symbol": self._spec.stooq_symbol,
            "endpoint": url,
            "etag": resp.etag,
            "last_modified": resp.last_modified,
            "license_note": (
                "stooq redistribution under "
                "data/s4_0/free_source/licence_clearance/"
                "owner_clearance_decision.md; "
                "free_source_rehearsal_only; not for real-capital execution"
            ),
            "spine_forbidden_uses": [
                "real_capital_execution",
                "evidence_grade_futures_replay",
            ],
            "target_variable": self._spec.target_variable,
        }
        # latency_guard_minutes = 0 at v1.0 because stooq EOD is itself
        # ~24h-lagged from CME settlement; an additional guard is redundant.
        # The field is set explicitly so a non-zero guard added later
        # propagates correctly through pit_manifest.usable_after_ts (matching
        # the CL spine wrapper at v2/ingest/cl_front_eod_pit.py).
        return [
            FetchResult(
                source=self._spec.pit_source,
                dataset=self._spec.pit_dataset,
                series=self._spec.pit_series,
                release_ts=release_ts,
                usable_after_ts=release_ts,
                revision_ts=None,
                data=df,
                provenance=provenance,
                vintage_quality=vq,
                observation_start=df["observation_date"].min(),
                observation_end=df["observation_date"].max(),
            )
        ]

    def close(self) -> None:
        if self._owns_http:
            self._http.close()
