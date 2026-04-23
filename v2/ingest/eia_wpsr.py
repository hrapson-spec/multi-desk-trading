"""EIA Weekly Petroleum Status Report ingester.

Release cadence: Wednesday >=10:30 ET (calendar: eia_wpsr.yaml).
Series consumed by oil_wti_5d / prompt_balance_nowcast:
    - crude_stocks, gasoline_stocks, distillate_stocks
    - refinery_runs
    - crude_imports, crude_exports

Network implementation: deferred. The EIA publishes WPSR tables as
structured HTML tables at
https://www.eia.gov/petroleum/supply/weekly/
and provides a structured API at
https://www.eia.gov/opendata/ (free, registration-gated key).

Operator action required before promotion:
    1. Register at https://www.eia.gov/opendata/ and store the key in
       ~/.config/v2/operator.yaml as `eia_api_key`.
    2. Implement `EIAWPSRIngester.fetch` against the API, not the HTML
       page (HTML scraping is brittle and not a stable promotion path).
    3. Record scraper_version in provenance on every fetch.
"""

from __future__ import annotations

from v2.ingest.base import BaseIngester


class EIAWPSRIngester(BaseIngester):
    name = "eia_wpsr"
    source = "eia_wpsr"
