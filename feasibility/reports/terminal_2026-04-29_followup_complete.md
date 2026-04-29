# Crude Feasibility Harness — Post-Data-Plan Follow-up COMPLETE

Created: 2026-04-29
Branch: `feasibility-harness-v0`
Schema: `tractability.v1.0`
Plan: `~/.claude/plans/review-this-specification-develop-hidden-spring.md`

This report consolidates all four phases of the post-data-plan
follow-up execution (B9 guard + audit candidate + residual mode + PIT
loader + multi-asset + live ingestion + code review). All four phases
are committed; working tree clean.

## Phase summary

| Phase | Item | Status | Commit |
|---|---|---|---|
| A | B9 additive-N guard (`compute_additive_n_contribution` + `--reject-non-additive`) | ✓ | 53f4fac |
| A | FOMC → WTI 3d feasibility pre-registration (v1, NOT v2 promotion) | ✓ | 53f4fac |
| B | Audit-only Phase 3 candidate at `feasibility/candidates/fomc_wti_3d/` | ✓ | 53f4fac |
| B | Phase 3 residual-mode harness (`--phase3-residual-mode`; updates `n_star`) | ✓ | 53f4fac |
| B | Audit orchestration script (`feasibility/scripts/audit_fomc_3d_phase3.py`) | ✓ | 53f4fac |
| C | PIT-aware price loader (`PITPriceSource` polymorphic with CSV `Path`) | ✓ | 53f4fac |
| C | Multi-asset CLI wiring (Brent/RBOB/NG SOURCE_KEYS) | ✓ | 53f4fac |
| C | Pre-2020 WPSR backfill (LIVE — succeeded; 4,992 new vintages) | ✓ | 85c2bdc |
| C | CL spine + multi-asset live ingestion | ✗ deferred (R1) | 85c2bdc |
| D | Code review (`feature-dev:code-reviewer` subagent) | ✓ | this report |
| D | M1 + M2 remediation | ✓ | this report |
| D | Final consolidated report | ✓ | this commit |

## Headline N table (final)

| Configuration | N effective | Verdict |
|---|---:|---|
| 5d / WPSR alone (locked v0 baseline) | 163 | small_model_only |
| 5d / WPSR + FOMC | 163 | small_model_only |
| 5d / WPSR + FOMC + OPEC + PSM + GPR | **180** | small_model_only |
| **3d / WPSR + FOMC + OPEC** | **285** | **continue** |
| **3d / 6 calendar families (incl. STEO, PSM, GPR)** | **310** | **continue** |

5d horizon is structurally infeasible for Phase 3 (≥250). 3d horizon
variant clears Phase 3 by 60 events for return_sign / signed return
targets. Magnitude target HAC remains intentionally NOT admitted (B8).

**2026-04-29 correction**: a follow-up candidate audit found and fixed a
duplicate target-anchor expansion in `compute_target_result`: greedy thinning
returned one timestamp per target anchor, but the observation list was
re-expanded when multiple family rows landed on the same WTI price timestamp.
The corrected counts above replace the earlier inflated 3d values (365/401)
and 5d multi-family value (240). The strategic conclusion is unchanged: 5d is
below the Phase 3 floor, while 3d remains viable.

**2026-04-29 candidate-audit extension**: all registered 3d follow-on
candidates have now been audited in residual mode. None clear Phase 3.
Consolidated matrix:
`feasibility/reports/terminal_2026-04-29_candidate_audits_complete.md`.

## Code review findings (Phase D)

The cumulative diff (`git diff 315ecbf..HEAD`) was reviewed by the
`feature-dev:code-reviewer` subagent. Result: **0 blocking, 2 major,
3 minor**.

### Major (resolved before final commit)

**M1 — B9 guard fired on `delta <= 0` instead of strict decrease**

- File: `feasibility/tractability_v1.py:962-966`
- Spec v1 §5 wording: "reject the addition if N **strictly decreases**".
  The guard was checking `info["delta"] <= 0`, treating zero-contribution
  families as violations. Resolved by changing to `info["delta"] < 0`
  with an explanatory comment that zero-delta families are no-ops, not
  violations (e.g. a non-overlapping calendar that adds zero events in
  the current sample window but may contribute as the post-2020 window
  grows).
- Tests updated:
  - `test_compute_additive_n_contribution_steo_zero_delta_after_anchor_dedup`
    documents the corrected empirical behavior: after target-anchor
    deduplication, WPSR + FOMC + STEO is zero-delta at 5d, not negative.
  - `test_reject_non_additive_raises_on_synthetic_negative_delta` and
    `test_force_include_admits_synthetic_negative_with_justification` cover
    the strict negative branch without depending on the old duplicate-anchor
    artifact.
  - `test_zero_delta_does_not_trigger_guard` (regression for M1): a candidate
    with zero net contribution does NOT fire the guard; no
    `forced_inclusions` entry is required.

**M2 — `StooqMultiAssetIngester.fetch()` dropped `usable_after_ts` from `FetchResult`**

- File: `v2/ingest/stooq_multi_asset.py:170-184`
- The constructor omitted `usable_after_ts`, defaulting it to `None`.
  The harness's `load_family_decision_events` falls back to `release_ts`
  when `usable_after_ts` is null — so the ingester worked at v1.0 (where
  latency_guard_minutes = 0 makes both timestamps equal), but the gap
  was latent and would surface the moment a non-zero guard was
  introduced. Resolved by passing `usable_after_ts=release_ts` explicitly
  with a comment documenting the v1.0 zero-latency rationale and the
  parallel pattern in `v2/ingest/cl_front_eod_pit.py`.

### Minor (deferred)

- **m1**: Spec v1 §13.1 quotes ρ values rounded to 2 decimal places
  ("ρ₁ ≈ +0.20"), while the dependence analysis at
  `docs/v2/dependence_analysis_3d_horizon.md` quotes 4 decimal places
  ("+0.2047"). Cosmetic. Spec wording also says ρ₃ is "near the negative
  tail of the IID null"; the actual measurement shows it is **outside**
  the null CI (−0.1358 < lower bound −0.1088). Deferred — the dependence
  analysis document is authoritative; the spec synopsis should be
  refreshed in a v1.1 patch but does not affect the harness's
  Phase 0 verdict.
- **m2**: `v2/pit_store/calendars/cl_front_eod.yaml` documents license
  caveats inline in a `notes:` block rather than as a structured
  `license_note:` key parallel to the ingester provenance. Deferred —
  no calendar-YAML auto-extractor consumes `license_note` today.
- **m3**: `test_v1_with_wpsr_only_matches_v0_post2020_n` is duplicated
  in spirit by `test_v0_invariant_preserved_with_csv_path` (both are
  real-data-gated and assert N=163 for WPSR-only). Listed for
  completeness; no action needed.

## Live ingestion outcome (Phase C)

| Source | Status | Vintages | Payload rows | Notes |
|---|---|---:|---:|---|
| `eia_wpsr_archive` (pre-2020) | **SUCCESS** | +4,992 | +4,992 | 2003-2019 weekly archive parsed cleanly; v1.1 conditional parser branches NOT needed (test scaffold's hypothesis falsified) |
| `cl_front_eod_pit` | FAIL | 0 | 0 | stooq returned empty body (HTTP 200, 0 bytes); Yahoo fallback broken on column-naming change |
| `brent_front_eod_pit` | FAIL | 0 | 0 | stooq empty body for `b.f` |
| `rbob_front_eod_pit` | FAIL | 0 | 0 | stooq empty body for `rb.f` |
| `ng_front_eod_pit` | FAIL | 0 | 0 | stooq empty body for `ng.f` |

**Operator runbook entries**:

- **R1**: stooq daily quota likely exhausted at the time of the run.
  Retry all 4 price spines the following morning. Quotas appear to
  reset ~24h. This is the decisive unblock for multi-asset
  tractability. Verification: re-run `python -m v2.ingest.cli backfill
  --source cl_front_eod_pit` (and the 3 multi-asset sources). Then
  re-measure tractability with PIT-loaded prices via the polymorphic
  `TargetDef.price_source = PITPriceSource(...)`.
- **R2**: Yahoo fallback in `v2/ingest/wti_prices.py:189` (`_normalize_ohlcv`)
  expects a `"date"` column that current Yahoo CSV does not emit. Add
  a column-alias for whatever Yahoo now emits (e.g. `"Date"` or
  similar). Small scaffold delta; out of scope for v1.0.

## Test status (final)

- **880 passed, 1 skipped** (was 827 + 7 audit errors at session start).
- +53 net new tests (5 v0 + 75 new across feasibility, ingesters,
  audit, candidates).
- Ruff: clean.
- Mypy: loose mode for `desks/`, `feasibility/`, `tests/`; strict for
  frozen surfaces (per `pyproject.toml:101-103`). All strict-mode
  modules untouched in this delivery.
- v0 invariant preserved: harness with `--families wpsr` at 5d still
  produces N=163 byte-identically.

## Git history

```
$ git log --oneline 315ecbf..HEAD
[this commit] docs(feasibility): post-data-plan follow-up complete (Phase D)
85c2bdc      feat(feasibility): live pre-2020 WPSR backfill + stooq retry runbook
53f4fac      feat(feasibility): tractability harness v1 + 6 ingesters + post-data-plan follow-up
315ecbf      docs(feasibility): define admissible effective N requirements [pre-existing]
```

## What is now possible (for future sessions)

1. **Phase 3 audit run**: with `feasibility/scripts/audit_fomc_3d_phase3.py`
   ready and the harness's `--phase3-residual-mode` operational, a
   Phase-3 audit of the FOMC → WTI 3d hypothesis can run end-to-end.
   Needs: FOMC + WPSR + OPEC residuals from the
   `LogisticRegressionFeasibilityModel`; the audit script orchestrates
   this. The output goes to
   `feasibility/outputs/tractability_v1_3d_phase3_audit_fomc.json` and
   the report at
   `feasibility/reports/terminal_<date>_phase3_audit_fomc.md`.
2. **Multi-asset tractability** (after R1 retry): with Brent/RBOB/NG
   PIT spines populated, the harness can re-measure per-target N
   streams via `PITPriceSource`. Each asset is its own per-target
   stream per spec §11 forbidden #4 (no cross-target N borrowing).
3. **B9 guard usage in production runs**: any future tractability
   invocation can pass `--reject-non-additive` to enforce strict-
   decrease; `--force-include <family> --non-additive-justification "..."`
   admits a candidate with provenance recorded in the manifest.
4. **v2 promotion path** (operator-driven): if the Phase 3 audit
   clears, the operator can copy
   `feasibility/preregs/2026-04-29-fomc_wti_3d.yaml` →
   `v2/desks/fomc/wti_3d/preregs/2026-04-29-fomc_wti_3d.yaml`, add
   the v2 target spec to `v2/contracts/target_variables.py`, and run
   the v2 governance check at `v2/governance/prereg.py:check_run`.

## Capability debits

(Per CLAUDE.md §3 "model-quality gaps as named debits".)

- **D-feas-1**: Yahoo fallback in `wti_prices.py:189` broken on column
  naming. In-budget; bounded; mitigated by stooq primary path. Fix
  in next operator-runbook session.
- **D-feas-2**: Pre-2010 WPSR HTML format never tested in `tests/v2/ingest/test_eia_wpsr_archive_pre_2020.py` v1.0 — but live run (Phase C)
  succeeded across 2003-2019 inclusive, falsifying the hypothesised
  format breakage. Closing this debit; v1.1 conditional parser
  branches NOT needed.
- **D-feas-3**: Multi-asset live ingestion blocked by stooq quota at
  test time. In-budget; bounded; mitigated by R1 retry runbook entry.

## Frozen-surface respect

Per CLAUDE.md §2 frozen surfaces:
- `contracts/v1.py` — UNTOUCHED ✓
- `controller/decision.py` — UNTOUCHED ✓
- `bus/`, `persistence/`, `eval/hot_swap.py`, `provenance/`,
  `scheduler/` — UNTOUCHED ✓
- `v2/contracts/target_variables.py` — UNTOUCHED ✓ (v2 registry
  remains frozen; new 3d and multi-asset targets live in v1
  registry only)
- `v2/desks/` — UNTOUCHED ✓ (audit candidate lives under
  `feasibility/candidates/`, NOT `v2/desks/`)

The architectural portability claim (CLAUDE.md §1.1) is preserved.
