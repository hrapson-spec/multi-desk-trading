# Operator runbook — public-data ingestion (v2 Phase B2b)

**Date:** 2026-04-25
**Audience:** the operator running the v2 public-data ingestion layer for the first time on a fresh machine.

## When to run this — strategic positioning (added 2026-04-26)

This stack is the **H5 substrate** in the revised next-step sequence introduced under the
2026-04-25 diagnosis revision. See the D-S4-3 entry in
[`docs/capability_debits.md`](../capability_debits.md) and the revised plan at
`~/.claude/plans/do-you-have-access-serene-pearl.md` for the full framing.

**Do not run the backfill or `build-features` commands below until H1, H2, and H4 have
resolved.** Specifically:

- **H1** — σ-calibration test (one-line patch at `v2/s4_0/model_quality.py:172`),
  isolating mechanism B.
- **H2** — distribution-shape variants, isolating mechanism A.
- **H4** — horizon test.

The reason is **confound isolation**: if H5 features are consumed before mechanisms A
(distribution shape) and B (σ-calibration) are falsified, a failed feature-augmented run
cannot distinguish between feature inadequacy and unresolved A/B defects. H5 may not be
reached at all if A and B alone close the debit.

Once H1, H2, and H4 are complete, this stack is the canonical PIT-safe path for ingesting
CFTC, EIA, FRED, Baker Hughes, and CME-public-metadata features. The structural gates
(leakage test, rights guardrail, registry validator) are green as of 2026-04-26 (tag
`v2-public-wti-data-stack-0.1`, 364/364 v2 tests passing, ruff clean).

The remainder of this runbook (API key provisioning, backfill commands, failure modes)
describes the H5 procedure for when it becomes the active step.

## 1. API key provisioning

Two keys are required:

- **FRED API key.** Register at https://research.stlouisfed.org/docs/api/api_key.html. Free; instant issuance.
- **EIA API key.** Register at https://www.eia.gov/opendata/register.php. Free; email confirmation.

Store both in `~/.config/v2/operator.yaml`:

```yaml
fred_api_key: "..."
eia_api_key: "..."
```

The file should be `chmod 600`. The loader is `v2/ingest/_secrets.py::get_api_key(name)`.

## 2. Verify install

```bash
python -c "from v2.ingest._secrets import get_api_key; print(get_api_key('fred')[:4]+'...')"
python -c "from v2.ingest._secrets import get_api_key; print(get_api_key('eia')[:4]+'...')"
```

Both should print a 4-character prefix followed by `...`. If you see `MissingAPIKeyError`, check `~/.config/v2/operator.yaml` exists and contains the relevant key.

## 3. Backfill commands

Run each source separately so manifest writes are atomic per source:

```bash
python -m v2.ingest.cli backfill --source fred --since 2000-01-01
python -m v2.ingest.cli backfill --source eia --since 2000-01-01
python -m v2.ingest.cli backfill --source cftc_cot --since 2009-09-01
python -m v2.ingest.cli backfill --source wti_prices
python -m v2.ingest.cli backfill --source baker_hughes
python -m v2.ingest.cli backfill --source cme_cl_metadata
```

Notes:

- The Baker Hughes archive URL pattern is publisher-controlled; if the default URL fails, supply the URL manually with `--archive-url <url>` or download the XLSX yourself and pass `--manual-xlsx-path /path/to/archive.xlsx`.
- `cme_cl_metadata` is a static reference fetch; only contract-spec metadata is written, not market data. The runtime regex enforces this — any attempt to write a forbidden column (`price`, `quote`, `bid`, `ask`, `settle`, `settlement`, `volume`, `vol`, `open_interest`, `oi`, `trade_count`, `last_trade_price`) raises before write.
- `wti_prices` is a convenience source that joins the FRED WTI series with derived columns; it does not call any new API beyond the standard FRED ingester.

## 4. Build features

```bash
python -m v2.ingest.cli build-features --grid daily --start 2010-01-01 --end <today>
```

This runs `v2/ingest/public_feature_join.py`, which uses `PITReader.as_of(...)` for backward-as-of joins. Only `model_eligible: true` registry entries are joined; display-only and manual-only entries are filtered out by the rights gate.

## 5. Verify outputs

Expected artefacts:

- `data/public/normalized/<source>/*.parquet` — per-source normalised partitions.
- `data/public/normalized/<source>/manifest.json` — manifest with row counts, date ranges, and any `last_run_failed_series` entries.
- `data/public/feature_sets/wti_public_features_daily.parquet` — joined feature set.

Confirm each manifest has `last_run_failed_series: []` (or reconcile against the EIA series-finder if not).

## 6. Failure modes

- **`MissingAPIKeyError`.** Check `~/.config/v2/operator.yaml` exists and the relevant key is set.
- **`BakerHughesURLNotConfiguredError`.** The default archive URL is unreachable. Either (a) discover the new archive URL on https://rigcount.bakerhughes.com/ and supply `--archive-url`, or (b) download the XLSX manually and supply `--manual-xlsx-path`.
- **EIA 404 on a series.** Cross-reference the failing series ID against the registry; if the registry note flags `verify_series_id_at_first_fetch`, the EIA series ID has likely been retired or renamed. The failed IDs are recorded in `last_run_failed_series` in the EIA manifest. Reconcile against the EIA series-finder, then update the registry YAML and re-run.
- **CME ingester raises on forbidden column.** Means the upstream HTML changed shape and a price/quote column appeared in the parsed metadata. **Do not bypass the regex.** Update the parser to drop the new column at the source, then re-run.
- **Empty FRED `SP500` history.** FRED limits this series to a ~10y trailing window; the registry pins `history_start: 2013-01-02` but the actual floor floats. Verify by re-checking https://fred.stlouisfed.org/series/SP500 and adjust the backfill `--since` accordingly.

## 7. Calendar mismatch carry-over (operator-visible)

The release calendar at `v2/pit_store/calendars/eia_wpsr.yaml` declares `source: eia_wpsr`, but the EIA ingester writes manifests with `source: eia`. **This is intentional at v2.0.** Calendar-keyed lookups for non-WPSR EIA series will not find the WPSR calendar; that is expected, since non-WPSR EIA series have different cadences and would need their own calendars.

**v2.1 follow-up:** split the EIA calendar by cadence (weekly WPSR, monthly STEO, etc.) and align the calendar `source` field to the manifest `source`.

## 8. Cross-references

- Inventory: `docs/v2/public_data_inventory.md`
- Rights matrix: `docs/v2/public_data_rights_and_limitations.md`
- Feature dictionary: `docs/v2/public_feature_dictionary.md`
- Live ingest results template: `docs/v2/public_data_ingestion_results.md`
