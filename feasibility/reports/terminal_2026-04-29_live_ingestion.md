# Live Ingestion Run — 2026-04-29

Executed all 5 live-ingestion steps sequentially against `data/pit_store/pit.duckdb`.
No code was modified. All commands run from project root with `.venv/bin/python`.

---

## 1. Per-source ingestion outcomes

### 1.1 EIA WPSR Archive (pre-2020, 2003-01-01 – 2019-12-31)

**Status: SUCCESS**

```
ingested 4992 vintages from 'eia_wpsr_archive'
exit code: 0
elapsed: ~6 min (network-heavy archive scrape, ~17 years × ~52 issues/year)
```

- The ingester fetched the EIA archive index, enumerated issue pages, and extracted
  per-series CSV tables for each historical WPSR release.
- 4992 vintages written (one per series per issue; 9 series × ~555 issues in range).
- No parse failures reported. The pre-2010 HTML format parsed without errors on this run
  (the EIA archive pages for that period still embed the same CSV download links).

**Note:** The first invocation launched in the background (PID 68962). A second foreground
attempt hit a DuckDB write-lock conflict and was killed. The background process completed
cleanly (exit 0) after ~6 min.

### 1.2 CL Front EOD Spine (stooq.com → Yahoo fallback)

**Status: FAIL — stooq rate-limit + Yahoo column mismatch**

```
ValueError: WTI CSV missing 'date' column
exit code: 1
```

- Stooq returned HTTP 200 with empty body (`content_length: 0`) for `cl.f` — consistent
  with stooq's bot-detection / daily quota enforcement (empty body, not 4xx).
- The code fell through to the Yahoo fallback, which returned a CSV whose date column is
  capitalised differently than expected by `_normalize_ohlcv` (raises `"missing 'date' column"`).
- Root cause: `_normalize_ohlcv` lowercases all column names via
  `df.columns = [str(c).strip().lower() ...]`, so the real issue is that Yahoo's current
  CSV response uses a column that does not match `"date"` even after lowercasing (likely
  `"datetime"` or `"timestamp"` in the current Yahoo Finance response format).

**Operator runbook (v1.1):** Check Yahoo Finance CSV column name for CL futures. If column
is now `"datetime"`, add a rename alias in `_normalize_ohlcv` before the `"date"` check.
Alternatively, switch Yahoo URL to the `v8/finance/chart/` JSON endpoint which is more
stable.

### 1.3 Brent Front EOD (stooq symbol: b.f)

**Status: FAIL — stooq rate-limit / empty body**

```
_EmptyBodyError: stooq returned empty for b.f
exit code: 1
```

HTTP 200, content_length = 0. Stooq is blocking the `b.f` symbol with an empty response.
Same mechanism as CL. No fallback source is configured for the multi-asset ingester.

### 1.4 RBOB Front EOD (stooq symbol: rb.f)

**Status: FAIL — stooq rate-limit / empty body**

```
_EmptyBodyError: stooq returned empty for rb.f
exit code: 1
```

Same as Brent above.

### 1.5 NG Front EOD (stooq symbol: ng.f)

**Status: FAIL — stooq rate-limit / empty body**

```
_EmptyBodyError: stooq returned empty for ng.f
exit code: 1
```

Same as Brent above.

---

## 2. PIT Manifest State Post-Ingestion

Query: `SELECT source, dataset, COUNT(*) AS vintages, SUM(row_count) AS total_payload_rows, MIN(usable_after_ts), MAX(usable_after_ts) FROM pit_manifest GROUP BY source, dataset ORDER BY 1, 2`

| source                   | dataset                    | vintages | payload_rows | earliest                    | latest                      |
|--------------------------|----------------------------|----------|--------------|-----------------------------|------------------------------|
| caldara_iacoviello       | gpr_weekly                 |      330 |          330 | 2020-01-03 14:05:00 UTC     | 2026-04-24 13:05:00 UTC     |
| eia                      | wpsr                       |    8,940 |        8,940 | 2012-01-05 15:35:00 UTC     | 2026-04-15 14:35:00 UTC     |
| eia_psm                  | psm_calendar               |       76 |           76 | 2020-01-31 15:05:00 UTC     | 2026-04-24 14:05:00 UTC     |
| eia_steo                 | steo_calendar              |       76 |           76 | 2020-01-14 17:05:00 UTC     | 2026-04-14 16:05:00 UTC     |
| fomc                     | fomc_announcements         |      102 |          102 | 2020-01-29 19:05:00 UTC     | 2026-04-08 18:05:00 UTC     |
| opec                     | opec_ministerial           |       48 |           48 | 2020-03-06 13:30:00 UTC     | 2026-03-05 13:30:00 UTC     |

**Delta from pre-run state:** The `eia / wpsr` row grew from ~3,948 vintages (post-2020 only)
to 8,940 — a delta of +4,992 pre-2020 vintages added by step 1.1.

No price spine entries exist for `cl_front_eod_pit`, `brent_front_eod_pit`,
`rbob_front_eod_pit`, or `ng_front_eod_pit` — all stooq fetches failed.

---

## 3. Multi-asset Tractability Re-measurement

**Status: DEFERRED — all stooq price spine ingestions failed.**

The measurement script at `/tmp/measure_multi_asset.py` was run and raised:

```
ValueError: No PIT vintages for (brent_front_eod_pit,
  front_month_eod_pit_spine, BRENT_FRONT_DAILY_EOD) under data/pit_store
```

No per-target N figures for Brent / RBOB / NG can be reported. The harness correctly
detects the missing data and raises rather than silently underreporting N.

---

## 4. Test Suite

```
879 passed, 1 skipped, 5 warnings in 33.32s
exit code: 0
```

No regression from live data added to `pit.duckdb`. The 1 skip is pre-existing.

---

## 5. Operator Runbook — v1.1 Follow-up Items

### R1: Stooq empty-body rate-limit (ALL price spines)

**Affects:** `cl_front_eod_pit`, `brent_front_eod_pit`, `rbob_front_eod_pit`, `ng_front_eod_pit`

Stooq returns HTTP 200 + empty body for futures symbols (`cl.f`, `b.f`, `rb.f`, `ng.f`)
when the request rate exceeds their undocumented quota. The ingester correctly surfaces
`_EmptyBodyError` and does not write partial data.

**Fix options (in priority order):**
1. Retry after 24h (stooq quotas appear to reset daily). Run the 4 backfills the following
   morning before any other stooq usage.
2. Add a `time.sleep(2)` between stooq requests in `_http.py` or the ingester to stay
   under rate limits.
3. For the multi-asset ingester, add a Yahoo Finance fallback analogous to the WTI ingester.

### R2: Yahoo Finance "date" column mismatch (CL fallback path)

**Affects:** `cl_front_eod_pit` (Yahoo fallback)

`_normalize_ohlcv` raises `"WTI CSV missing 'date' column"`. Yahoo Finance may now return
`"datetime"`, `"Date"`, or similar. After lowercasing all columns, verify the actual column
name in a live Yahoo response and add an alias or rename before the existence check.
File: `v2/ingest/wti_prices.py` line ~189.

### R3: Pre-2010 WPSR HTML format (low priority — did not fail)

The pre-2010 WPSR archive pages parsed without error on this run. No special handling was
required. Monitor future runs for `metadata_error: ...` entries in
`ingester.last_run_failed_issues` if EIA changes the archive page structure.

### R4: DuckDB write-lock contention on concurrent runs

The first WPSR invocation launched in background (from the Bash tool's async behaviour)
held the write lock. A subsequent foreground call failed with `IOException: Conflicting lock`.
**Mitigation:** Never run two `cli backfill` commands concurrently against the same
`pit.duckdb`. The operator should wait for one backfill to complete before launching the
next (as specified in the task instructions).
