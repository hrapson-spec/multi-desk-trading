# Public-data rights and limitations (v2 Phase B2b)

**Date:** 2026-04-25
**Phase context:** B2b public-data ingestion layer.
**Scope:** all sources enumerated in `v2/ingest/registry/public_data_inventory.yaml`.

**This document is normative.** Any ingester that does not align with the rights statements below is a regression. The registry validator and ingester runtime checks operationalise these statements; this document is the human-readable substrate.

## Per-source rights statements

### FRED (Federal Reserve Bank of St. Louis)

- **Rights status:** public domain under FRED terms of use; full attribution required.
- **Cite:** https://fred.stlouisfed.org/legal/
- **Use authorised in v2:** model features, redistribution, derived works (with attribution).
- **Registry entries:** `fred_dcoilwtico`, `fred_dcoilbrenteu`, `fred_vixcls`, `fred_dgs2`, `fred_dgs10`, `fred_t10y2y`, `fred_dfii10`, `fred_t10yie`, `fred_fedfunds`, `fred_sp500`, `fred_dtwexbgs`.
- **Ingester:** `v2/ingest/fred_alfred.py` (vintage-aware via ALFRED real-time periods).

### EIA (U.S. Energy Information Administration)

- **Rights status:** public domain.
- **Cite:** https://www.eia.gov/about/copyrights_reuse.php
- **Use authorised in v2:** model features, redistribution, derived works.
- **Registry entries:** all `eia_*` weekly petroleum status report series (12 entries).
- **Ingester:** `v2/ingest/eia_wpsr.py`, manifest `source="eia"`.

### CFTC Commitments of Traders

- **Rights status:** public; reuse permitted.
- **Cite:** https://www.cftc.gov/MarketReports/CommitmentsofTraders/
- **Use authorised in v2:** model features, redistribution, derived works.
- **Registry entries:** `cftc_cot_wti` (market code `067651`).
- **Ingester:** `v2/ingest/cftc_cot.py`.

### Cboe VIX historical (direct path)

- **Rights status:** display-permitted; **non-display redistribution requires a Cboe licence.**
- **Cite:** https://www.cboe.com/tradable_products/vix/vix_historical_data
- **Use authorised in v2:** display only — i.e. visual rendering on screens for the operator. **NOT model-eligible.**
- **Registry entry:** `cboe_vix_direct` carries `model_eligible: false` and exists only as a resilience fallback.
- **Canonical path for VIX-as-model-feature:** `fred_vixcls` (FRED-routed VIXCLS), which is public-domain under FRED's licence and therefore freely usable in models.
- **Ingester:** `v2/ingest/cboe_vix.py` (writes to a quarantined display-only manifest path; not consumed by `public_feature_join.py`).

### Baker Hughes (North America rig count)

- **Rights status:** free archive, attribution required.
- **Cite:** https://rigcount.bakerhughes.com/
- **Use authorised in v2:** model features, redistribution, derived works (with attribution).
- **Registry entries:** `baker_hughes_us_oil_rigs`, `baker_hughes_us_gas_rigs`, `baker_hughes_us_total_rigs`, `baker_hughes_canada_total_rigs`, `baker_hughes_na_total_rigs`.
- **Ingester:** `v2/ingest/baker_hughes_rig_count.py`.

### CME public contract metadata

- **Rights status:** spec/calendar pages publicly viewable. **Market data (prices, quotes, settlements, volume, open interest) is NOT authorised for non-display use without a CME licence.**
- **Cite:** https://www.cmegroup.com/markets/energy/crude-oil/light-sweet-crude.contractSpecs.html and https://www.cmegroup.com/market-data/license-data.html
- **Use authorised in v2:** static reference metadata only — contract unit, expiry rule, physical-settlement flag, last-trade-date list. **No price/quote/settle/volume/OI columns may be written.**
- **Registry entry:** `cme_cl_contract_metadata` carries `model_eligible: false`.
- **Ingester:** `v2/ingest/cme_contract_metadata_public.py`. Has a runtime regex that scans the parsed-row column set against a forbidden-column pattern (`price|quote|bid|ask|settle|settlement|volume|vol|open_interest|oi|trade_count|last_trade_price`) and **raises before write** on any match.

### OPEC MOMR / IEA OMR

- **Rights status:** manual-only. OPEC MOMR is freely viewable but PDF scraping is out of scope at v2.0; IEA OMR is paywalled for the full report.
- **Cite:** https://www.opec.org/opec_web/en/publications/202.htm and https://www.iea.org/reports/oil-market-report
- **Use authorised in v2:** release-day event flags only. The operator may record monthly headline-series numbers manually as event features.
- **Registry entries:** `opec_momr`, `iea_omr` carry `model_eligible: false` and `retrieval_method: manual_event_feature`.

## What this layer DOES NOT contain

Out of scope for v2 Phase B2b:

- Licensed CME tick data, order-book data, settlements, volumes, open interest.
- Bloomberg / Argus / Platts / Kpler / Vortexa data (paid commercial feeds).
- Databento / CQG / AlgoSeek tick or book products.
- ICE Brent settlements / open interest (licensed redistribution).
- Refinitiv / LSEG real-time feeds.
- Full-text scraping of OPEC MOMR PDFs or IEA OMR PDFs.
- Any other source whose redistribution is restricted or whose ToS prohibit model use.

If a future phase requires any of the above, it must (a) procure the licence, (b) move the source into a separately-permissioned ingester directory, and (c) update this document.

## Enforcement

Three layers enforce the rights matrix:

1. **Registry rights-gate validator (Pydantic).** `v2/ingest/public_data_registry.py` defines a `RegistryEntry` model with a validator that rejects any entry where `rights_status != "public" AND model_eligible=True`. This makes the legal substrate machine-checked at import time. Adding a non-public source as `model_eligible: true` is a load-time error.

2. **CME rights-check regex.** `v2/ingest/cme_contract_metadata_public.py` enforces that the CME ingester writes only metadata fields by scanning each row's column set against a forbidden-column regex. Any match raises before any rows are persisted, preventing accidental ingestion of non-display market data even if the upstream HTML changes shape.

3. **Leakage gate (PIT-safe join).** `tests/v2/ingest/test_public_feature_join_pit.py` verifies that `v2/ingest/public_feature_join.py` consumes only `model_eligible: true` registry entries via `PITReader.as_of(...)` and never leaks data with `release_ts > as_of_ts`. Display-only and manual-only entries are absent from the resulting feature frame by construction.

## Cross-references

- Inventory: `docs/v2/public_data_inventory.md`
- Per-feature semantics: `docs/v2/public_feature_dictionary.md`
- Operator runbook: `docs/v2/operator_runbook_public_data.md`
- Live ingest results: `docs/v2/public_data_ingestion_results.md`
