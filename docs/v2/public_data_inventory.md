# Public-data inventory (v2 Phase B2b)

**Date:** 2026-04-25
**Phase context:** B2b — public-data ingestion layer for the multi-desk-trading v2 redesign.
**Plan reference:** `~/.claude/plans/engineering-instruction-obtain-all-shimmying-liskov.md`
**Source of truth:** `v2/ingest/registry/public_data_inventory.yaml` (this file is a derived narrative; the YAML is authoritative).

This inventory enumerates every public-data series the v2 ingestion layer is designed to source. Entries flagged `model_eligible: true` are admissible into model features. Non-eligible entries (`display_only`, `manual_only`) are documented for resilience-fallback or release-event use only and are blocked from feature joins by the registry rights-gate validator (`v2/ingest/public_data_registry.py`).

## Summary

| Metric | Count |
| --- | --- |
| Total registry entries | 33 |
| Model-eligible | 29 |
| Display-only (excluded from models) | 2 |
| Manual-only (release-event flag only) | 2 |

Breakdown by source family:

| Source family | Entries | Model-eligible | Notes |
| --- | --- | --- | --- |
| FRED prices | 2 | 2 | DCOILWTICO, DCOILBRENTEU |
| FRED macro/risk | 9 | 9 | VIX, rates, breakeven, FX, S&P |
| EIA WPSR | 12 | 12 | Stocks, production, imports/exports, refining |
| CFTC COT | 1 | 1 | WTI 067651 disaggregated |
| Cboe VIX (direct) | 1 | 0 | Resilience fallback only |
| Baker Hughes rig count | 5 | 5 | US oil/gas/total + Canada + NA |
| CME public CL metadata | 1 | 0 | Specs/calendar only; no market data |
| OPEC MOMR / IEA OMR | 2 | 0 | Manual release-event flags only |

## FRED prices

| Key | Series | Description | Frequency | History start | Rights | Eligible | URL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `fred_dcoilwtico` | DCOILWTICO | Cushing OK WTI Spot Price FOB (USD/bbl) | daily | 1986-01-02 | public | yes | https://fred.stlouisfed.org/series/DCOILWTICO |
| `fred_dcoilbrenteu` | DCOILBRENTEU | Brent Crude Oil Spot Price (USD/bbl) | daily | 1987-05-20 | public | yes | https://fred.stlouisfed.org/series/DCOILBRENTEU |

## FRED macro / risk

| Key | Series | Description | Frequency | History start | Rights | Eligible | URL |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `fred_vixcls` | VIXCLS | CBOE VIX (FRED-routed) — canonical model-eligible VIX path | daily | 1990-01-02 | public | yes | https://fred.stlouisfed.org/series/VIXCLS |
| `fred_dgs2` | DGS2 | 2Y Treasury constant-maturity rate | daily | 1976-06-01 | public | yes | https://fred.stlouisfed.org/series/DGS2 |
| `fred_dgs10` | DGS10 | 10Y Treasury constant-maturity rate | daily | 1962-01-02 | public | yes | https://fred.stlouisfed.org/series/DGS10 |
| `fred_t10y2y` | T10Y2Y | 10Y minus 2Y Treasury yield spread | daily | 1976-06-01 | public | yes | https://fred.stlouisfed.org/series/T10Y2Y |
| `fred_dfii10` | DFII10 | 10Y TIPS yield | daily | 2003-01-02 | public | yes | https://fred.stlouisfed.org/series/DFII10 |
| `fred_t10yie` | T10YIE | 10Y breakeven inflation rate | daily | 2003-01-02 | public | yes | https://fred.stlouisfed.org/series/T10YIE |
| `fred_fedfunds` | FEDFUNDS | Effective Fed Funds rate | monthly | 1954-07-01 | public | yes | https://fred.stlouisfed.org/series/FEDFUNDS |
| `fred_sp500` | SP500 | S&P 500 close (FRED-routed; ~10y trailing window) | daily | 2013-01-02 | public | yes | https://fred.stlouisfed.org/series/SP500 |
| `fred_dtwexbgs` | DTWEXBGS | Nominal Broad USD Index (goods+services) | daily | 2006-01-02 | public | yes | https://fred.stlouisfed.org/series/DTWEXBGS |

Notes:
- `fred_sp500`: FRED limits `SP500` to a ~10-year trailing window; treat `history_start` as floating.
- `fred_dtwexbgs`: substitute `DTWEXAFEGS` if discontinued.
- `fred_vixcls` is the canonical model-eligible VIX. `cboe_vix_direct` exists only as a resilience fallback and is `model_eligible: false`.

## EIA Weekly Petroleum Status Report (WPSR)

All EIA series carry `notes: "verify_series_id_at_first_fetch"` where flagged below — operators must confirm the series ID resolves on first live fetch and record the failed IDs in `last_run_failed_series` if not.

| Key | Series | Description | History start | URL | Verify on first fetch |
| --- | --- | --- | --- | --- | --- |
| `eia_wcestus1` | WCESTUS1 | U.S. ending crude stocks excl. SPR (kbbl) | 1982-08-20 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCESTUS1&f=W | (no flag) |
| `eia_wcsstus1` | WCSSTUS1 | U.S. SPR ending crude stocks (kbbl) | 1982-08-20 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCSSTUS1&f=W | (no flag) |
| `eia_cushing_stocks` | W_EPC0_SAX_YCUOK_MBBL | Cushing OK ending crude stocks (kbbl) | 2004-04-09 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=W_EPC0_SAX_YCUOK_MBBL&f=W | (no flag) |
| `eia_us_crude_production_weekly` | WCRFPUS2 | U.S. weekly crude field production (kbbl/d) | 1983-01-07 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCRFPUS2&f=W | YES |
| `eia_us_crude_imports_weekly` | WCRIMUS2 | U.S. weekly crude imports (kbbl/d) | 1990-01-05 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCRIMUS2&f=W | YES |
| `eia_us_crude_exports_weekly` | WCREXUS2 | U.S. weekly crude exports (kbbl/d) | 1990-01-05 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WCREXUS2&f=W | YES |
| `eia_refinery_utilisation_weekly` | WPULEUS3 | U.S. weekly refinery operable-capacity utilisation (%) | 1989-01-06 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WPULEUS3&f=W | YES |
| `eia_us_gasoline_stocks_weekly` | WGTSTUS1 | U.S. weekly total gasoline stocks (kbbl) | 1990-08-31 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WGTSTUS1&f=W | YES |
| `eia_us_distillate_stocks_weekly` | WDISTUS1 | U.S. weekly distillate stocks (kbbl) | 1982-08-20 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WDISTUS1&f=W | YES |
| `eia_us_jet_stocks_weekly` | WKJSTUS1 | U.S. weekly jet-fuel stocks (kbbl) | 1990-08-31 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WKJSTUS1&f=W | YES |
| `eia_us_propane_stocks_weekly` | WPRSTUS1 | U.S. weekly propane/propylene stocks (kbbl) | 1993-10-01 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WPRSTUS1&f=W | YES |
| `eia_us_product_supplied_total_weekly` | WRPUPUS2 | U.S. weekly total products supplied (proxy demand, kbbl/d) | 1991-02-08 | https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=WRPUPUS2&f=W | YES |

All EIA series: weekly cadence, public domain, `model_eligible: true`, calendar `eia_wpsr.yaml`.

## CFTC Commitments of Traders

| Key | Series | Description | Frequency | History start | Rights | Eligible |
| --- | --- | --- | --- | --- | --- | --- |
| `cftc_cot_wti` | 067651 | NYMEX WTI Light Sweet Crude COT, disaggregated, futures-only | weekly | 2006-06-13 | public | yes |

Source URL: https://www.cftc.gov/dea/newcot/FinFutWk.txt
Calendar: `cftc_cot.yaml`. Distinguish `report_date` (positions as of Tuesday) from `publication_date` (Friday 15:30 ET); the PIT eligibility rule prohibits treating COT data as contemporaneous with the report Tuesday.

## Cboe VIX (direct, resilience fallback only)

| Key | Series | Description | Frequency | History start | Rights | Eligible |
| --- | --- | --- | --- | --- | --- | --- |
| `cboe_vix_direct` | VIX | Cboe VIX historical CSV — display-permitted only | daily | 1990-01-02 | display_only | **no** |

Source URL: https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv
Calendar: `cboe_vix.yaml`. **Not model-eligible at v2.0.** The canonical model path is `fred_vixcls`. Cboe-direct is retained for resilience fallback only.

## Baker Hughes North America rig count

| Key | Series | Description | Frequency | History start | Rights | Eligible |
| --- | --- | --- | --- | --- | --- | --- |
| `baker_hughes_us_oil_rigs` | us_oil_rigs | U.S. oil rigs (Friday) | weekly | 1987-07-17 | public | yes |
| `baker_hughes_us_gas_rigs` | us_gas_rigs | U.S. gas rigs (Friday) | weekly | 1987-07-17 | public | yes |
| `baker_hughes_us_total_rigs` | us_total_rigs | U.S. total rigs (Friday) | weekly | 1987-07-17 | public | yes |
| `baker_hughes_canada_total_rigs` | canada_total_rigs | Canada total rigs (Friday) | weekly | 2000-01-07 | public | yes |
| `baker_hughes_na_total_rigs` | na_total_rigs | NA total rigs (Friday) | weekly | 2000-01-07 | public | yes |

Source URL (all): https://rigcount.bakerhughes.com/na-rig-count
Calendar: `baker_hughes_rig_count.yaml`. Retrieval is XLSX archive download; URL pattern is publisher-controlled and may shift (manual-XLSX fallback supported).

## CME public CL contract metadata

| Key | Series | Description | Frequency | Rights | Eligible |
| --- | --- | --- | --- | --- | --- |
| `cme_cl_contract_metadata` | CL | CME Light Sweet Crude Oil contract specification metadata | irregular | display_only | **no** |

Source URLs:
- https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html
- https://www.cmegroup.com/market-data/license-data.html

Metadata fields only: contract unit, expiry rule, physical-settlement flag, last-trade-date list. **Non-display market data (prices, settlements, volumes, open interest) is NOT authorised under CME's public terms.** The `cme_contract_metadata_public.py` ingester has a runtime regex that rejects forbidden price/quote columns. Calendar: `cme_cl_contract_metadata.yaml`.

## OPEC MOMR / IEA OMR (manual release-event flags only)

| Key | Series | Description | Frequency | Rights | Eligible |
| --- | --- | --- | --- | --- | --- |
| `opec_momr` | MOMR | OPEC Monthly Oil Market Report — release-day flag only | monthly | manual_only | **no** |
| `iea_omr` | OMR | IEA Oil Market Report — release-day flag only (full report paywalled) | monthly | manual_only | **no** |

Source URLs:
- https://www.opec.org/opec_web/en/publications/202.htm
- https://www.iea.org/reports/oil-market-report

No PDF scraping is implemented at v2.0. Operators may record monthly headline series manually as event features via `event_calendar.yaml`.

## Cross-references

- Rights matrix and enforcement: `docs/v2/public_data_rights_and_limitations.md`
- Per-feature semantics, transformations, and PIT rules: `docs/v2/public_feature_dictionary.md`
- Operator first-run runbook: `docs/v2/operator_runbook_public_data.md`
- Live ingest results template: `docs/v2/public_data_ingestion_results.md`
