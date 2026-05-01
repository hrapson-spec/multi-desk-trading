# Feasibility Harness v1 — Progress Summary

Created: 2026-04-29
Schema: `tractability.v1.0`

This report consolidates the v1 tractability work completed in one
build session against the plan at
`~/.claude/plans/review-this-specification-develop-hidden-spring.md`.

## Headline N table (post-2020 effective events per target)

| Configuration | Distinct events | Effective N | sign HAC | mag HAC | Verdict |
|---|---:|---:|---:|---:|---|
| 5d / WPSR only (locked v0 baseline) | 327 | **163** | 147 | 66 | small_model_only |
| 5d / WPSR + FOMC | 429 | **207** | 154 | 82 | small_model_only |
| 5d / WPSR + FOMC + OPEC | 477 | **209** | 163 | 77 | small_model_only |
| 5d / WPSR + FOMC + STEO | 505 | **198** ⚠️ | 140 | 73 | small_model_only |
| **3d / WPSR + FOMC + OPEC** | 477 | **365** | 268 | 133 | **continue** |
| 3d / WPSR + FOMC + STEO + OPEC | 553 | **360** | 272 | 131 | continue |

⚠️ STEO is net-negative at 5d under greedy thinning (see B9).

## Verdict shifts

- **5d horizon (current spec)**: hard ceiling around N = 210 with
  realistically ingestible free-data event families. EIA-914 +
  pre-2020 backfill + GPR cannot together close the 41-event gap to
  Phase 3 entry (≥250).
- **3d horizon (Tier 3.A proposed amendment)**: WPSR + FOMC + OPEC
  alone delivers N = 365, clearing Phase 3 by 115 events and
  approaching Phase 4 (≥500). The 3d variant is the structural fix.

## What was built

### Tier 1.C — Multi-family tractability harness v1 (completed)
- `feasibility/tractability_v1.py` — multi-family registry, Newey-West
  HAC (ρ_k capped at 0), circular block bootstrap (B=2000),
  §12-compliant manifest, vintage-quality filter, Phase 0 vs Phase 3+
  N_star separation, `--horizon-days` CLI flag for Tier 3.A demos.
- `tests/feasibility/test_tractability_v1.py` — 18 tests including
  v0/v1 invariant test on the real PIT store.

### Tier 1.A — Three event-family ingesters (completed)
1. **FOMC** (`v2/ingest/fomc_calendar.py`) — 102 events (51 statements +
   51 minutes) post-2020. **+44 effective N** (matches plan
   estimate). vintage_quality = `true_first_release`.
2. **STEO** (`v2/ingest/eia_steo_calendar.py`) — 76 monthly events
   post-2020. **−9 effective N** under greedy thinning (B9 finding).
   vintage_quality = `release_lag_safe_revision_unknown` (v1.0
   computes 2nd-Tuesday rule; v1.1 will scrape archive).
3. **OPEC ministerial** (`v2/ingest/opec_ministerial_calendar.py`) —
   48 curated events post-2020. **+2 effective N** under greedy
   thinning (events cluster on 1st-5th of month, overlapping FOMC).
   vintage_quality = `release_lag_safe_revision_unknown` (v1.0 =
   curated list; v1.1 will scrape opec.org/press_room).

Calendar YAMLs, CLI registration, and unit tests delivered for each.
Total: 35 new ingester tests pass.

### Tier 3.A — 3d horizon variant (CLI capability only)
- Added `--horizon-days` flag to harness CLI.
- Empirically demonstrates the structural fix predicted in the plan.
- **Spec amendment doc not yet authored**.
- **Dependence-analysis doc not yet authored**.
- **Target registry update at `contracts/target_variables.py` not
  yet done** (would add `WTI_FRONT_3D_LOG_RETURN`).

## Spec issues discovered (added to plan §B)

- **B8** (§1 vs §6 vs §9): At Phase 0 there is no validation score
  series, so spec §6 HAC adjustment cannot be applied to model
  residuals (because no model exists). v1 applies HAC to raw target
  series as a Phase-3-readiness diagnostic only; `n_star` at Phase 0
  is `n_after_purge_embargo`. Recommended spec amendment wording is
  in plan §F1.
- **B9** (§5): Greedy thinning is non-monotone in event additions.
  Empirical: STEO addition reduces N from 207 to 198. OPEC addition
  on top of WPSR+FOMC adds only +2. Recommended spec amendments:
  (a) document non-monotone behaviour and require additive-N
  pre-screen; (b) use shorter horizon (Tier 3.A) so cooldown < 7
  days.

## What remains in the plan

| Tier | Item | Status | Estimated effort |
|---|---|---|---|
| 1.A | EIA-914 PSM ingester | not started | 1 day |
| 1.B | CL front EOD PIT spine | not started | 1 day |
| 1.D | Run multi-family tractability + verify Phase 3 (5d) | n/a — proven impossible at 5d | — |
| 2.A | Pre-2020 WPSR backfill | not started | 1.5 days |
| 2.B | Caldara-Iacoviello GPR | not started | 0.5 days |
| 3.A | 3d horizon spec amendment + dependence analysis + target registry | CLI only; spec docs missing | 1 day to finish |
| 3.B | Multi-asset target streams (Brent, RBOB, NG) | not started | 2 days |

## Files modified or added

```
feasibility/tractability_v1.py                                   (new)
feasibility/outputs/tractability_v1_baseline_wpsr_only.json      (new)
feasibility/outputs/tractability_v1_wpsr_plus_fomc.json          (new)
feasibility/outputs/tractability_v1_wpsr_fomc_opec.json          (new)
feasibility/outputs/tractability_v1_wpsr_plus_fomc_plus_steo.json (new)
feasibility/outputs/tractability_v1_3d_horizon.json              (new)
feasibility/outputs/tractability_v1_3d_all_families.json         (new)
feasibility/reports/terminal_2026-04-29_tractability_v1_baseline.md (new)
feasibility/reports/terminal_2026-04-29_tractability_v1_wpsr_plus_fomc.md (new)
feasibility/reports/terminal_2026-04-29_tractability_v1_progress_summary.md (this file)
v2/ingest/fomc_calendar.py                                       (new)
v2/ingest/eia_steo_calendar.py                                   (new)
v2/ingest/opec_ministerial_calendar.py                           (new)
v2/pit_store/calendars/fomc.yaml                                 (new)
v2/pit_store/calendars/eia_steo.yaml                             (new)
v2/pit_store/calendars/opec_ministerial.yaml                     (new)
v2/ingest/cli.py                                                 (3 sources registered)
tests/feasibility/test_tractability_v1.py                        (new, 18 tests)
tests/v2/ingest/test_fomc_calendar.py                            (new, 12 tests)
tests/v2/ingest/test_eia_steo_calendar.py                        (new, 13 tests)
tests/v2/ingest/test_opec_ministerial_calendar.py                (new, 10 tests)
data/pit_store/pit.duckdb                                        (added 226 rows)
```

Total tests added: **53** (all pass alongside existing 5 v0 tests).

## Decision points for the user

1. **Phase 3 entry path**: 5d horizon is structurally infeasible with
   free post-2020 data. Either commit to Tier 3.A (3d horizon spec
   amendment) or accept that Phase 3 candidate audit cannot proceed.
   Tier 3.A is the cleanest path; Tier 1.A EIA-914 + Tier 2.A
   pre-2020 backfill provide marginal improvement only.
2. **STEO retention**: STEO is net-negative as a decision-event
   family. Recommend keeping the ingestion (useful as a feature
   input) but excluding from the default tractability registry.
3. **OPEC v1.1 upgrade**: v1.0 OPEC dates are curated and
   approximate. Live archive scraping would lift vintage to
   `true_first_release`. Low priority given low effective-N yield.

## Reproducibility

```
cd multi-desk-trading
.venv/bin/python -m v2.ingest.cli backfill --source fomc_calendar --since 2020-01-01 --until 2026-04-29
.venv/bin/python -m v2.ingest.cli backfill --source eia_steo_calendar --since 2020-01-01 --until 2026-04-29
.venv/bin/python -m v2.ingest.cli backfill --source opec_ministerial_calendar --since 2020-01-01 --until 2026-04-29
.venv/bin/python -m feasibility.tractability_v1 --families wpsr,fomc,opec_ministerial --horizon-days 3 --purge-days 3 --embargo-days 3
.venv/bin/pytest tests/feasibility/ tests/v2/ingest/test_fomc_calendar.py tests/v2/ingest/test_eia_steo_calendar.py tests/v2/ingest/test_opec_ministerial_calendar.py -v
```

Same git commit on the same PIT manifest produces byte-identical
JSON output (modulo `created_at_utc` and `git_commit`).
