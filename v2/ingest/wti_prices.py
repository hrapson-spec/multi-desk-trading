"""WTI front-month futures price ingester (Yahoo/stooq).

Release cadence: daily after CME EOD (~14:30 ET for settlement).
Series: settlement close for the active front-month WTI contract (CL1)
under roll_rule_v1 (pending spec artefact under v2/desks/oil/.../mechanism.md).

Network implementation: deferred. Candidate free sources:
    - Yahoo Finance: https://finance.yahoo.com/quote/CL%3DF (HTML/JSON)
    - stooq: https://stooq.com/q/?s=cl.f (CSV)
Both are free and redistribute CME EOD settlement with typical <24h
lag. An intraday tick is NOT admissible; the ingester must reject any
payload whose provenance declares intraday or live.

Operator action required before promotion:
    1. Pick a primary + fallback source and commit the choice in the
       desk's prereg.
    2. Implement roll_rule_v1 (business-day-before-expiry, or settled
       contract with highest OI) as a pure function in this module.
    3. The fetch() must emit release_ts at the CME settlement time for
       the retrieved bar, not at the time the ingester made the HTTP
       call. A holiday with no settlement must emit no FetchResult.
"""

from __future__ import annotations

from v2.ingest.base import BaseIngester


class WTIPricesIngester(BaseIngester):
    name = "wti_prices"
    source = "wti_front_month"
