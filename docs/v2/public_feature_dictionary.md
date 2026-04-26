# Public-feature dictionary (v2 Phase B2b)

**Date:** 2026-04-25
**Phase context:** B2b ingestion layer — every model-eligible registry entry is documented below with semantics, transformation, release timing, and PIT availability rule.
**Source of truth:** `v2/ingest/registry/public_data_inventory.yaml` and `v2/pit_store/calendars/*.yaml`.

## Naming convention

Post-join column name: `{source}__{series}__value` (double underscores).
Derived features append a transformation suffix: `..._z52w`, `..._wow`, `..._crowding`, `..._days_since_release`.

## Universal PIT availability rule

For every feature, eligibility at evaluation timestamp `as_of_ts` is governed by the rule established in each calendar YAML and applied by `PITReader.as_of(...)` (`v2/pit_store/reader.py:88`):

```
known_by_ts = COALESCE(revision_ts, release_ts)
row eligible at as_of_ts iff release_ts <= as_of_ts AND known_by_ts <= as_of_ts
```

Calendars supply per-source `release_ts` semantics; vintage-aware sources (FRED ALFRED) supply both `release_ts` and a per-row `vintage_date`. `public_feature_join.py` uses backward as-of semantics — never forward-fills past `as_of_ts`.

## Universal missing-data handling

- FRED API returns string `"."` for missing observations → coerced to NaN at parse time.
- EIA API returns JSON null → coerced to NaN at parse time.
- CFTC CSV missing columns → row dropped at parse time; failures recorded in manifest.
- Baker Hughes XLSX gaps → preserved as NaN; PIT join treats NaN as "no observation" rather than 0.

## FRED price features

### `fred__DCOILWTICO__value`
- **Description:** Cushing OK WTI spot price FOB (USD/bbl).
- **Source / series:** FRED / `DCOILWTICO`. Raw field: `value`. Transformation: none (raw).
- **Frequency:** daily. **Release timing:** see `fred_alfred.yaml` (irregular per-series; `lag_to_publication_days: 0` per ALFRED vintage).
- **Reason for inclusion:** primary public WTI proxy; load-bearing for the oil desk feature surface.
- **Known risks:** FRED occasionally re-vintages the series; ALFRED captures the vintage.

### `fred__DCOILBRENTEU__value`
- **Description:** Brent crude oil spot price (USD/bbl).
- **Source / series:** FRED / `DCOILBRENTEU`. Raw field: `value`.
- **Frequency:** daily. **History start:** 1987-05-20.
- **Reason for inclusion:** Brent–WTI spread proxy.
- **Known risks:** none beyond standard FRED vintage drift.

## FRED macro / risk features

### `fred__VIXCLS__value`
- **Description:** CBOE VIX daily close, FRED-routed.
- **Source / series:** FRED / `VIXCLS`. Raw field: `value`.
- **Frequency:** daily. **History start:** 1990-01-02.
- **Reason for inclusion:** **canonical model-eligible VIX path** (Cboe-direct is display-only and not model-eligible).
- **Known risks:** none.

### `fred__DGS2__value`, `fred__DGS10__value`, `fred__T10Y2Y__value`
- **Descriptions:** 2Y, 10Y constant-maturity Treasury yields, and the 10Y-2Y spread.
- **Source:** FRED. **Frequency:** daily.
- **Reason for inclusion:** rates curve / recession-risk proxy.
- **Known risks:** Treasury auction days can revise prior values modestly.

### `fred__DFII10__value`, `fred__T10YIE__value`
- **Descriptions:** 10Y TIPS yield and 10Y breakeven inflation.
- **Source:** FRED. **Frequency:** daily. **History start:** 2003-01-02.
- **Reason for inclusion:** real-rate / inflation channel.

### `fred__FEDFUNDS__value`
- **Description:** Effective Fed Funds Rate.
- **Frequency:** monthly. **History start:** 1954-07-01.
- **Reason for inclusion:** policy-rate baseline.
- **Known risks:** monthly cadence; PIT availability rule pins the row to its publication month.

### `fred__SP500__value`
- **Description:** S&P 500 daily close (FRED-routed).
- **Frequency:** daily. **History start:** 2013-01-02.
- **Reason for inclusion:** equity-vs-oil cross-asset proxy.
- **Known risks:** **FRED limits SP500 to a ~10y trailing window;** treat `history_start` as floating. The registry pins the floor but operators must verify on each backfill. Long-history equity exposure must be reconstructed from a separate (licensed) source if needed.

### `fred__DTWEXBGS__value`
- **Description:** Nominal Broad U.S. Dollar Index (goods+services basket).
- **Frequency:** daily. **History start:** 2006-01-02.
- **Reason for inclusion:** USD strength / commodity-price-channel proxy.
- **Known risks:** if discontinued, substitute `DTWEXAFEGS`.

## EIA WPSR features

All EIA features share calendar `eia_wpsr.yaml`: weekly Wednesday 10:30 ET release, `lag_to_publication_days: 5` (week ending the prior Friday), holiday rule shifts to next business day. PIT availability follows `known_by_ts = COALESCE(revision_ts, release_ts)`.

| Feature column | Series | Description | History start | Verify-on-first-fetch |
| --- | --- | --- | --- | --- |
| `eia__WCESTUS1__value` | WCESTUS1 | U.S. ending crude stocks excl. SPR (kbbl) | 1982-08-20 | no |
| `eia__WCSSTUS1__value` | WCSSTUS1 | U.S. SPR ending crude stocks (kbbl) | 1982-08-20 | no |
| `eia__W_EPC0_SAX_YCUOK_MBBL__value` | W_EPC0_SAX_YCUOK_MBBL | Cushing OK ending crude stocks (kbbl) | 2004-04-09 | no |
| `eia__WCRFPUS2__value` | WCRFPUS2 | U.S. weekly crude field production (kbbl/d) | 1983-01-07 | YES |
| `eia__WCRIMUS2__value` | WCRIMUS2 | U.S. weekly crude imports (kbbl/d) | 1990-01-05 | YES |
| `eia__WCREXUS2__value` | WCREXUS2 | U.S. weekly crude exports (kbbl/d) | 1990-01-05 | YES |
| `eia__WPULEUS3__value` | WPULEUS3 | Refinery operable-capacity utilisation (%) | 1989-01-06 | YES |
| `eia__WGTSTUS1__value` | WGTSTUS1 | Total gasoline stocks (kbbl) | 1990-08-31 | YES |
| `eia__WDISTUS1__value` | WDISTUS1 | Distillate stocks (kbbl) | 1982-08-20 | YES |
| `eia__WKJSTUS1__value` | WKJSTUS1 | Jet-fuel stocks (kbbl) | 1990-08-31 | YES |
| `eia__WPRSTUS1__value` | WPRSTUS1 | Propane/propylene stocks (kbbl) | 1993-10-01 | YES |
| `eia__WRPUPUS2__value` | WRPUPUS2 | Total products supplied (proxy demand, kbbl/d) | 1991-02-08 | YES |

For each EIA feature: raw field is the API `value` field; transformation is none for the raw column; missing observations are NaN.

**Known risks:** all EIA series flagged `verify_series_id_at_first_fetch` may resolve to 404 if the EIA series ID has been retired or renamed. The ingester records failed series IDs in `last_run_failed_series` in the manifest; operators must reconcile against the EIA series-finder before re-running.

## CFTC COT features

### `cftc__067651__managed_money_long`, `cftc__067651__managed_money_short`, `cftc__067651__open_interest`, `cftc__067651__commercial_long`, `cftc__067651__commercial_short`
- **Description:** WTI Light Sweet Crude COT positioning (disaggregated, futures-only).
- **Source / series:** CFTC / market code `067651`. Raw fields: `M_Money_Positions_Long_All`, `M_Money_Positions_Short_All`, `Open_Interest_All`, `Prod_Merc_Positions_Long_All`, `Prod_Merc_Positions_Short_All` (verify exact column names against CFTC schema on first fetch).
- **Frequency:** weekly. **Release timing:** Friday 15:30 ET; `lag_to_publication_days: 3` (positions as of Tuesday prior). Calendar `cftc_cot.yaml`.
- **PIT availability:** never treat COT positions as contemporaneous with the report Tuesday. The `report_date` field (Tuesday) is the **observation period**; the `publication_date` field (Friday) is the **release_ts**. The PIT join uses `release_ts`, not `report_date`.
- **Reason for inclusion:** speculative positioning channel; forms the basis for the COT crowding indicator (see derived features).
- **Known risks:** rare publisher reissue with `revision_ts`; federal shutdown suspends publication.

## Baker Hughes features

| Feature column | Series | Description | History start |
| --- | --- | --- | --- |
| `baker_hughes__us_oil_rigs__value` | us_oil_rigs | U.S. oil rigs (Friday) | 1987-07-17 |
| `baker_hughes__us_gas_rigs__value` | us_gas_rigs | U.S. gas rigs (Friday) | 1987-07-17 |
| `baker_hughes__us_total_rigs__value` | us_total_rigs | U.S. total rigs | 1987-07-17 |
| `baker_hughes__canada_total_rigs__value` | canada_total_rigs | Canada total rigs | 2000-01-07 |
| `baker_hughes__na_total_rigs__value` | na_total_rigs | NA total rigs | 2000-01-07 |

- **Raw field:** rig count integer parsed from XLSX archive.
- **Transformation:** none for raw.
- **Frequency:** weekly. **Release timing:** Friday 13:00 ET, `lag_to_publication_days: 0`. Calendar `baker_hughes_rig_count.yaml`.
- **PIT availability:** standard `known_by_ts` rule.
- **Reason for inclusion:** lead indicator on shale supply.
- **Known risks:** publisher URL pattern shifts; manual-XLSX fallback path supported (`--manual-xlsx-path`).

## Derived features

The join layer emits the following derived columns alongside raw values.

### Rolling 52-week z-score: `..._z52w`

For every weekly feature `x_t`, define:

```
z52w_t = (x_t - mean_{t-52w..t}(x)) / std_{t-52w..t}(x)
```

Computed strictly on rows already eligible under the PIT rule (no peeking). NaN until 52 prior eligible observations exist.

### Week-on-week delta: `..._wow`

For every weekly feature: `wow_t = x_t - x_{t-1w}`. Where `t-1w` denotes the prior weekly observation by `release_ts`.

### COT crowding indicator: `cftc__067651__crowding`

```
crowding_t = (managed_money_long_t - managed_money_short_t) / open_interest_t
```

Bounded in `[-1, 1]`. NaN if `open_interest_t == 0` or any input is NaN. Computed at the COT publication timestamp.

### Days-since-release counters: `event__{calendar}__days_since_release`

Derived deterministically from `event_calendar.py`:
- `event__eia_wpsr__days_since_release`
- `event__cftc_cot__days_since_release`
- `event__baker_hughes__days_since_release`
- `event__cl_expiry__days_since_release` (CME CL contract expiry from metadata)
- `event__opec_momr__days_since_release`
- `event__iea_omr__days_since_release`

Each counter increments by 1 each calendar day after the release event and resets to 0 on the next release. Forms the basis for event-time conditioning in models.

## Cross-references

- Inventory and source URLs: `docs/v2/public_data_inventory.md`
- Rights status and enforcement: `docs/v2/public_data_rights_and_limitations.md`
- Operator first-run instructions: `docs/v2/operator_runbook_public_data.md`
- Live ingest results: `docs/v2/public_data_ingestion_results.md`
