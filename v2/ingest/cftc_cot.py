"""CFTC Commitments of Traders ingester.

Release cadence: Friday >=15:30 ET (calendar: cftc_cot.yaml).
Observation semantics: positions as of Tuesday prior.

Network implementation: deferred. CFTC publishes structured CSV archives
at https://www.cftc.gov/dea/newcot/deacot.txt (current) and
https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
(historical annuals). Both are free and open.

Operator action required before promotion:
    1. Implement CFTCCOTIngester.fetch to pull the disaggregated,
       futures-only WTI contract code (currently '067651' for CL on
       NYMEX — verify).
    2. Explicitly set release_ts to the publisher's release_ts on
       Friday 15:30 ET; never ingest with a release_ts earlier than
       that, even if the CSV appears on the server earlier.
"""

from __future__ import annotations

from v2.ingest.base import BaseIngester


class CFTCCOTIngester(BaseIngester):
    name = "cftc_cot"
    source = "cftc_cot"
