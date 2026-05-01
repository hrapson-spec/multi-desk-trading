# v2 data contract

**Status**: D1 paper artefact. Read-only.
**Tag**: `v2-contracts-0.1`
**Scope**: every feature used by every v2 desk.
**Deviation policy**: changes require a typed deviation record under the
(pending) promotion lifecycle; no silent drift.

---

## 1. What this contract is

This document defines the canonical shape of the v2 point-in-time (PIT)
feature store. It is the centre of the v2 architecture, not an attachment
to the model layer. No v2 desk may read from any source that does not
satisfy this contract.

### 1.1 Storage model

- **Canonical truth**: immutable Parquet files on disk, one file per
  `(source, release_ts)` pair. Never overwritten; new vintages append new
  files.
- **Query engine**: DuckDB views/macros over the Parquet corpus. DuckDB is
  stateless w.r.t. truth; re-creating DuckDB from scratch over the same
  Parquet corpus must produce byte-identical query results.
- **Manifest**: a single DuckDB table (`pit_manifest`) indexing every raw
  vintage file. Append-only.
- **Derived features**: materialised in a `pit_derived` namespace. Always
  rebuildable from raw truth; never treated as canonical.

### 1.2 Risk acceptance: test-validated calendar

Release-calendar correctness is validated in the test suite, **not** at
runtime. The `PITReader` query API does not refuse out-of-vintage reads.
Correctness rests on:
  - per-source YAML calendar declarations (§4);
  - a mandatory test pack that exercises every desk's feature path under
    boundary vintage cases;
  - the Layer-1 PIT audit (`v2/audit/pit_audit.py`) required for every
    promotion.

This is a deliberate trade: runtime-gated enforcement was rejected in the
10-round brainstorm in favour of ergonomic research workflows plus test
discipline. Any future promotion that cannot meet the test burden must
escalate to runtime gating via a contract deviation.

---

## 2. Manifest schema

```sql
CREATE TABLE pit_manifest (
    manifest_id      TEXT PRIMARY KEY,       -- uuid
    source           TEXT NOT NULL,          -- e.g. "eia", "cftc_cot"
    dataset          TEXT,                   -- e.g. "wpsr", "steo", "disaggregated"
    series           TEXT,                   -- optional intra-source key
    release_ts       TIMESTAMP NOT NULL,     -- publisher's release timestamp (UTC)
    usable_after_ts  TIMESTAMP,              -- release_ts plus latency guard, if any
    revision_ts      TIMESTAMP,              -- when a revision superseded this vintage, if any
    observation_start DATE,                  -- earliest observation this file covers
    observation_end   DATE,                  -- latest observation this file covers
    schema_hash      TEXT NOT NULL,          -- SHA-256 of the Parquet schema
    row_count        BIGINT NOT NULL,
    checksum         TEXT NOT NULL,          -- SHA-256 of the Parquet bytes
    ingest_ts        TIMESTAMP NOT NULL,     -- when v2 ingested it (UTC)
    provenance       TEXT NOT NULL,          -- JSON: {url, method, scraper_version, ...}
    parquet_path     TEXT NOT NULL,          -- path relative to pit_root
    vintage_quality  TEXT NOT NULL,          -- true_first_release | release_lag_safe_revision_unknown | ...
    superseded_by    TEXT,                   -- manifest_id of newer vintage, if any
    UNIQUE (source, dataset, series, release_ts, revision_ts)
);
```

### 2.1 Vintage invariants

- A row with `revision_ts = NULL` represents a **first-release** vintage.
- A row with a non-null `revision_ts` represents a **revision** that
  superseded an earlier vintage. Both rows remain in the manifest.
- `superseded_by` is set on the older row when a revision arrives. The
  revision row's `superseded_by` is `NULL` until a further revision
  supersedes it.
- `checksum` is the SHA-256 of the raw Parquet bytes after ingest. Any
  mismatch at read time is a hard-fail condition for the consuming desk.
- `usable_after_ts` is the timestamp used by `PITReader.as_of`. For WPSR,
  it is `release_ts + latency_guard_minutes`.
- `vintage_quality` is monotonic downstream: feature views, forecasts,
  run manifests, and reports may degrade it but may not drop or improve it.

---

## 3. Parquet layout

```
pit_root/
    raw/
        eia/
            dataset=wpsr/
            series=WCESTUS1/
            release_ts=2026-01-14T15:30:00Z/
                data.parquet
        cftc_cot/
            dataset=disaggregated/
            release_ts=2026-01-16T20:30:00Z/
                data.parquet
        fred_alfred/
            series=DCOILWTICO/
                release_ts=2026-01-15T12:00:00Z/
                    data.parquet
        wti_front_month/
            release_ts=2026-01-15T20:15:00Z/
                data.parquet
    derived/
        {family}/
            {materialisation_name}/
                as_of=YYYY-MM-DD/
                    data.parquet
```

- Raw files are immutable after ingest.
- Partition keys reflect the publisher's release timestamp in UTC, not the
  observation date.
- Derived files are rebuildable; they may be deleted and regenerated at
  any time.

---

## 4. Release-calendar declaration

One YAML file per source under `v2/pit_store/calendars/`. Example:

```yaml
# v2/pit_store/calendars/eia_wpsr.yaml
source: eia
dataset: wpsr
description: "EIA Weekly Petroleum Status Report (U.S. crude/product balances)"
publisher: "U.S. Energy Information Administration"
latency_guard_minutes: 5
holiday_handling: "official_issue_date_or_schedule"
release_cadence:
  type: weekly
  weekday: wednesday
  earliest_release_time_et: "10:30"
  holiday_rule: "shift_next_business_day"
observation_semantics:
  reporting_period: "week_ending_friday_prior"
  lag_to_publication_days: 5
revision_policy: "ad_hoc_small_revisions_possible"
pit_eligibility_rule: |
  For decision timestamp t (UTC), a row with usable_after_ts u is
  decision-eligible iff u <= t and COALESCE(revision_ts, u) <= t.
source_confidence:
  baseline: 0.95
  degradation_conditions:
    - "federal shutdown (EIA suspends publication)"
    - "scheduled methodology change within 2 weeks"
data_quality_multipliers:
  fresh: 1.0
  stale_1week: 0.85
  stale_2week: 0.60
  stale_over_2week: 0.0       # hard gate
```

Every source used by any v2 desk must have a calendar. The Layer-1 audit
checks each desk's features against these calendars and refuses promotion
if any feature path has no calendar entry.

---

## 5. Query API

### 5.1 DuckDB macros (stable contract)

```sql
-- Return the decision-eligible row for (source, dataset, series) as of the given
-- UTC timestamp. Respects supersession.
SELECT * FROM as_of('eia.wpsr.WCESTUS1', TIMESTAMP '2026-04-23 21:00:00Z');

-- Return the latest vintage released strictly before the given timestamp.
SELECT * FROM latest_available_before('fred.DCOILWTICO', '2026-04-23T08:00:00Z');

-- Diff two vintages of the same series; used by the PIT auditor.
SELECT * FROM vintage_diff('eia.wpsr.WCESTUS1',
                           '2026-01-14T15:30:00Z',
                           '2026-01-21T15:30:00Z');

-- Declared calendar metadata (read-only view over YAML).
SELECT * FROM release_calendar('eia.wpsr');
```

### 5.2 Python reader

`v2/pit_store/reader.py` wraps the above macros in a typed interface.
Every read call accepts an `as_of_ts: datetime` and returns a dataframe
plus a per-row `data_quality` struct.

---

## 6. Data-quality contract (per read)

Every row returned by the PIT reader carries a `data_quality` struct:

```
data_quality = {
    "source"              : str,
    "dataset"             : str | null,
    "release_ts"          : timestamp,
    "usable_after_ts"     : timestamp,
    "revision_ts"         : timestamp | null,
    "as_of_ts"            : timestamp,
    "freshness_state"     : "fresh" | "stale_1w" | "stale_2w" | "stale_over_2w",
    "release_lag_days"    : float,
    "missingness_mask"    : struct,
    "forward_fill_used"   : bool,
    "last_good_ts"        : timestamp,
    "source_confidence"   : float in [0,1],
    "quality_multiplier"  : float in [0,1],
    "decision_eligible"   : bool,
    "calendar_version"    : str,
    "checksum_verified"   : bool,
    "vintage_quality"     : str,
}
```

- `quality_multiplier` combines `freshness_state`, `source_confidence`, and
  `missingness_mask` per the source's YAML spec. A `quality_multiplier` of
  `0.0` is a hard-gate trigger, not a "soft degraded" state.
- `decision_eligible = false` means the row was retrievable but should not
  be used at this `as_of_ts`. The reader still returns it so the desk can
  record why it was rejected.
- `checksum_verified` is re-computed on read. A mismatch raises a
  `PITChecksumError` and must propagate as a data hard-gate trigger to the
  desk.

---

## 7. Replay and reproducibility

- Every decision event produced by v2 records the manifest IDs of every
  raw vintage read during its computation.
- Given the same `pit_root`, the same `as_of_ts`, and the same desk code
  hash, re-running must produce a byte-identical forecast.
- `v2/common/replay/` provides deterministic replay utilities re-pointed
  from v1's replay machinery. Replay hash mismatch is a hard-fail in the
  degradation ladder.

---

## 8. Degraded-mode rules

A desk's abstain policy against data degradation is:

| Condition | Policy |
|---|---|
| Required source has `quality_multiplier = 0` | Desk hard-gate → ABSTAIN; family propagates |
| `decision_eligible = false` for required row | Desk hard-gate → ABSTAIN |
| Checksum mismatch | Desk hard-gate → ABSTAIN; operational incident logged |
| Release-calendar version mismatch | Desk hard-gate → ABSTAIN; audit required |
| Required source stale but within `q > 0` bands | Desk proceeds; `q` flows into `data_quality_score` |

These rules are the minimum. Individual desk preregs may tighten them
(e.g. require `freshness_state = fresh` for a specific feature) but may
not weaken them.

---

## 9. PIT audit (Layer-1 gate)

Every promotion to State 2 (validated model) or higher requires a Layer-1
PIT audit report from `v2/audit/pit_audit.py`:

- Reconstructible vintage history for every feature used by the desk.
- Release-lag distribution per source.
- Revision statistics (count, magnitude) per source.
- Stale-data behaviour validation: simulated outages of each required
  source confirm the desk abstains.
- Schema / checksum coverage ≥ 100% on all consumed vintages.
- **Training-window determination**: the audit report names the earliest
  `as_of_ts` at which the desk's full feature view is reconstructible with
  full provenance. This defines the v2.0 training window (no prior
  estimate is declared here).

---

## 10. Forbidden at this contract version

- Reading FRED (current-value-only) where ALFRED (vintage) is available.
- Mutating a raw Parquet file after ingest (versioned revisions only).
- Using a revised value as if first-released, without a typed deviation.
- Any scraper that does not emit a `provenance` JSON including scraper
  version and source URL/method.
- Materialising a derived feature as "canonical" (delete + regenerate
  from raw truth must always succeed).
- Silent forward-fill across release boundaries without `forward_fill_used
  = true` and an accompanying quality penalty.
