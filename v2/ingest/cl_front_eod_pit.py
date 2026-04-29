"""CL front-month executable target PIT spine (v1.0).

Required by spec §4 for Phase 3 candidate audit. v1.0 is a thin
wrapper around ``v2.ingest.wti_prices.WTIPricesIngester`` (stooq cl.f
primary, Yahoo CL=F fallback) that re-emits the daily EOD payload
under the dedicated PIT spine namespace ``source=cl_front_eod_pit``,
``dataset=front_month_eod_pit_spine``, ``series=CL_FRONT_DAILY_EOD``.

Vintage handling at v1.0:
- Historical period (back to 2020-01-01 if available from stooq's
  archive): vintage_quality = ``release_lag_safe_revision_unknown``
  because stooq publishes the most recent settlement only; pre-launch
  history is what the source has now, not what was published at
  release_ts.
- Forward (post spine-go-live = today onward): future runs of this
  ingester capture each day's settlement as a true_first_release
  vintage.

Per spec §4 / data plan §D.5 forbidden_uses for the v1.0 spine:
- ``free_source_rehearsal_only`` — approved for paper backtesting
  rehearsal under
  `data/s4_0/free_source/licence_clearance/owner_clearance_decision.md`
- NOT approved for real-capital execution.
- NOT approved for evidence-grade S4-0 futures replay.

License clearance: stooq's cl.f redistributes CME EOD with <24h lag
and typical re-distribution constraints. See the licence-clearance
doc above before promoting any artefact built from this spine.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from v2.ingest._http import HTTPClient
from v2.ingest.base import BaseIngester, FetchResult
from v2.ingest.wti_prices import WTIPricesIngester
from v2.pit_store.manifest import PITManifest
from v2.pit_store.quality import VintageQuality
from v2.pit_store.writer import PITWriter

SCRAPER_VERSION = "v2.cl_front_eod_pit.0"


class CLFrontEODPITIngester(BaseIngester):
    """Re-emit `wti_prices` payload under the dedicated PIT spine namespace."""

    name = "cl_front_eod_pit"
    source = "cl_front_eod_pit"

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
        self._inner = WTIPricesIngester(writer, manifest, http=http)
        self._since = since
        self._until = until

    def fetch(self, as_of_ts: datetime | None = None) -> list[FetchResult]:
        inner_results = self._inner.fetch(as_of_ts=as_of_ts)
        re_emitted: list[FetchResult] = []
        today_utc = (as_of_ts or datetime.now(UTC)).date()
        for r in inner_results:
            df = r.data
            if "observation_date" in df.columns and not df.empty:
                if self._since is not None:
                    df = df[df["observation_date"] >= self._since]
                if self._until is not None:
                    df = df[df["observation_date"] <= self._until]
                if df.empty:
                    continue
                obs_start = df["observation_date"].min()
                obs_end = df["observation_date"].max()
            else:
                obs_start = r.observation_start
                obs_end = r.observation_end

            # Vintage logic: rows whose observation_date is "today" or
            # later get true_first_release semantics; older rows are
            # release_lag_safe_revision_unknown. Since this ingester is
            # a single-vintage emit per run, we determine the vintage
            # by the most-recent row's recency.
            most_recent = obs_end if obs_end else today_utc - timedelta(days=2)
            days_lag = (today_utc - most_recent).days if most_recent else 999
            if days_lag <= 1:
                vq = VintageQuality.TRUE_FIRST_RELEASE.value
            else:
                vq = VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN.value

            provenance = dict(r.provenance)
            provenance.update(
                {
                    "method": "cl_front_eod_pit_wrapper",
                    "scraper_version": SCRAPER_VERSION,
                    "underlying_source": r.source,
                    "underlying_dataset": r.dataset,
                    "license_note": (
                        "stooq cl.f redistribution under "
                        "data/s4_0/free_source/licence_clearance/"
                        "owner_clearance_decision.md; "
                        "free_source_rehearsal_only; not for real-capital execution"
                    ),
                    "spine_forbidden_uses": [
                        "real_capital_execution",
                        "evidence_grade_futures_replay",
                    ],
                }
            )
            re_emitted.append(
                FetchResult(
                    source=self.source,
                    dataset="front_month_eod_pit_spine",
                    series="CL_FRONT_DAILY_EOD",
                    release_ts=r.release_ts,
                    usable_after_ts=r.usable_after_ts,
                    revision_ts=r.revision_ts,
                    data=df,
                    provenance=provenance,
                    vintage_quality=vq,
                    observation_start=obs_start,
                    observation_end=obs_end,
                )
            )
        return re_emitted

    def close(self) -> None:
        self._inner.close()
