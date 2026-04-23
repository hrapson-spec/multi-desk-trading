"""FRED/ALFRED (Archival FRED) vintage-aware macro ingester.

Release cadence: irregular, series-specific (calendar: fred_alfred.yaml).
Unlike the other three ingesters, ALFRED exposes real-time periods and
vintage_date explicitly; a single network round-trip can return many
vintages for one series.

Network implementation: deferred. ALFRED endpoints:
    https://api.stlouisfed.org/fred/series/observations
        ?series_id=<id>
        &realtime_start=<date>
        &realtime_end=<date>
        &api_key=<key>&file_type=json

Operator action required before promotion:
    1. Register at https://research.stlouisfed.org/docs/api/api_key.html
       (free). Store key in ~/.config/v2/operator.yaml as `fred_api_key`.
    2. Implement FREDAlfredIngester.fetch to accept a `series_id` arg and
       return one FetchResult per vintage_date returned.
    3. Set release_ts = realtime_start of the returned vintage (its
       publication timestamp for that version of the data).
"""

from __future__ import annotations

from v2.ingest.base import BaseIngester


class FREDAlfredIngester(BaseIngester):
    name = "fred_alfred"
    source = "fred_alfred"
