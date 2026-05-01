# Public-data ingestion results (v2 Phase B2b)

**Date:** 2026-04-25
**Status:** Live ingest pending operator runbook execution. Structural gates green as of 2026-04-25; live first-run results to be filled in by operator after running `python -m v2.ingest.cli backfill --source <name>`.

This document is a TEMPLATE. The operator runs the runbook in `docs/v2/operator_runbook_public_data.md`, then updates this file in place with the live numbers.

## Structural test status (as of 2026-04-25)

- `tests/v2`: 364 passed.
- `tests/v2/ingest`: ~95 passed (subset of the above).
- `ruff check .`: clean.

## Ingest summary table (operator to fill)

| Source | Rows ingested | Earliest date | Latest date | Missing rows | Duplicate rows | release_ts confidence | Manifest path |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fred | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/normalized/fred/manifest.json` |
| eia | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/normalized/eia/manifest.json` |
| cftc_cot | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/normalized/cftc_cot/manifest.json` |
| wti_prices | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/normalized/wti_prices/manifest.json` |
| baker_hughes | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/normalized/baker_hughes/manifest.json` |
| cme_cl_metadata | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/normalized/cme_cl_metadata/manifest.json` |
| cboe_vix (display-only) | TBD | TBD | TBD | TBD | TBD | TBD | `data/public/quarantine/cboe_vix/manifest.json` |

## Skipped sources and reasons

- **Cboe VIX direct (`cboe_vix_direct`).** `display_only` rights status. FRED VIXCLS is the canonical model-eligible path. Cboe-direct ingester runs only when the operator opts into a quarantined display-only manifest.
- **OPEC MOMR (`opec_momr`)** and **IEA OMR (`iea_omr`).** `manual_only` rights status. PDF scraping is out of scope at v2.0. Operator records release-day flags via `event_calendar.yaml`.

## Tests passed / failed

- Structural: 364 passing (full `tests/v2`).
- Live: TBD (operator fills after running `cli backfill`).

## Rights / terms caveats

See `docs/v2/public_data_rights_and_limitations.md`. Of particular note:

- CME public ingester writes metadata only; the runtime regex blocks any forbidden price/quote columns.
- Cboe VIX direct is non-model-eligible; FRED VIXCLS is the canonical path.
- OPEC / IEA full reports are not scraped.

## Next steps

1. Operator provisions FRED and EIA API keys (see runbook).
2. Operator runs `python -m v2.ingest.cli backfill --source <name>` for each source.
3. Operator runs `python -m v2.ingest.cli build-features --grid daily --start 2010-01-01 --end <today>`.
4. Operator updates this file in place with the live row counts, dates, and manifest paths.
5. Capability debit `D-S4-3` mitigation log gets a follow-on dated row when the next WTI ridge rebuild consumes the new features.
