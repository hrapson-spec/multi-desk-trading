# Crude Feasibility Harness N Requirement Specification v1

Date: 2026-04-29
Scope: WTI/WPSR crude feasibility harness, multi-event-family
extension, 3d horizon variant
Status: amendments to the locked v0 spec at
`feasibility/reports/n_requirement_spec_v0.md`

## 0. Change log relative to v0

This v1 spec is **additive and clarifying**, not breaking. Every v0
verdict against the locked WPSR PIT store remains reproducible by
running v1 with `--families wpsr --horizon-days 5 --purge-days 5
--embargo-days 5`. The amendments below address the eight spec
issues surfaced during the v1 harness build (issues B1-B8 in the
data-acquisition plan, plus B9 discovered during Tier 1.A) and add
the 3d horizon variant required by the data plan §D.9.

| ID | v0 section | v1 amendment |
|---|---|---|
| A1 (B1, B2) | §6, §12 | §6 HAC effective-N implemented (Newey-West, ρ_k floor at 0); §12 mandatory manifest fields populated by harness v1.0 |
| A2 (B3) | §5 | Disambiguates "post-event greedy thinning" (count) vs. "walk-forward training-side exclusion" (training-set rule) |
| A3 (B4) | §4 | Generalises the "canonical observation" to multi-event-family: an event family is a `(source, dataset)` tuple with a single decision_ts derivation rule; per-target N is greedy-thinned across the union of all family decision timestamps |
| A4 (B5) | §7 | Recommends reporting MDE both vs. the observed positive rate AND vs. the naive 0.50 baseline, to surface optical sample-overfit |
| A5 (B6) | §11 #5 | Adds explicit stale-feature rejection rule for daily-target work |
| A6 (B7) | §6 | Lower-bounds ρ_k at 0 (capped) to prevent mean-reverting series from inflating N_eff |
| A7 (B8, NEW) | §6 + §1 + §9 | Phase 0 disposition: HAC reported on raw target as Phase-3-readiness diagnostic only; n_star at Phase 0 = N_after_purge_embargo; HAC enters n_star from Phase 3 onward where it is computed on validated model residuals |
| A8 (B9, NEW) | §5 | Documents non-monotone behaviour of greedy thinning: an event family addition can decrease retained N if its events fall in the cooldown windows of already-retained events. Requires "additive-N pre-screen" before family registration |
| A9 (NEW) | §13 | Adds horizon variant `WTI_FRONT_3D_LOG_RETURN` with `purge=3`, `embargo=3`. Backed by the dependence analysis at `docs/v2/dependence_analysis_3d_horizon.md` |

## 1. Executive Definition (unchanged from v0)

```
N_star = min_target(
    N_eff_oos_post2020_pit_clean_target_realizable_purged_embargoed_costed
)
```

Operating ranges, hard floors, and stop conditions are identical to
v0 §1. The only Phase 0 disposition change is the **interpretation**
of `N_eff` per the §6 amendment below.

## 2. Non-Admissible N (unchanged from v0)

## 3. Canonical Observation Unit (amended per A3)

The canonical observation is one **decision event** in some
**event family**. v0 wording specialised this to "one WPSR
decision event"; v1 generalises:

```
e_i = (
    decision_ts_i,
    family_i,                  # NEW: event family the observation belongs to
    PIT_snapshot_i,
    feature_vector_i,
    target_path_i,
    target_i
)
```

**Definition (event family):** A `(source, dataset)` tuple in the
PIT manifest, with a single release calendar (in
`v2/pit_store/calendars/<family>.yaml`) and a single canonical
`decision_ts = usable_after_ts = release_ts + latency_guard_minutes`
derivation rule.

**Combination rule (per spec §11 forbidden #4):** N is computed
**per target**, by greedy thinning across the union of decision
timestamps from all admitted families that share that target. N is
**not** combined across different targets.

Admitted families v1.0 (data plan Tier 1.A):

- `wpsr` — EIA Weekly Petroleum Status Report (Wednesdays)
- `fomc` — FOMC statements + minutes (irregular Wed/Thu)
- `opec_ministerial` — OPEC+ Ministerial / JMMC announcements (irregular)
- `steo` — EIA STEO monthly (2nd Tuesday) — **registered but flagged as net-negative for N at 5d** (see A8)

## 4. N Pipeline (unchanged structure; amended fields per A1)

Every report must emit the full N waterfall (v0 §4) plus the
mandatory v1 manifest fields per §12. v1.0 outputs include:

- `n_manifest_rows`
- `n_decision_timestamps`
- `n_targetable_raw_by_target`
- `n_post2020_raw_by_target`
- `n_after_quality_filter_by_target`
- `n_after_purge_embargo_by_target`
- `n_hac_or_block_adjusted_by_target` (Phase 0 disposition: diagnostic only — see §6 amendment)
- `n_oos_by_fold` (placeholder until fold structure is declared)
- `n_by_regime` (placeholder until regime registry is declared)
- `n_by_cost_bucket` (v1.0 placeholder cost model)
- `n_star`
- `vintage_quality_distribution`

## 5. Purge and Embargo Specification (amended per A2 and A8)

The formal definition is **unchanged** from v0:

```
E_i = [d_i - p, d_i + h + b]
```

Two events i and j cannot both contribute to independent validation
when their formal exclusion windows intersect.

**Implementation note** (new in v1): the harness implements two
distinct functions:

- `effective_n_post_event_greedy(events, purge_days, embargo_days)`
  applies the greedy "next_allowed = retained + purge + embargo" rule
  to count the maximum non-overlapping subset of events. This is what
  the harness reports as `n_after_purge_embargo`.
- `walk_forward_split(train_events, test_events, p, h, b)` applies
  the formal `E_i = [d_i − p, d_i + h + b]` rule to **training-side
  exclusion**. Out of scope for Phase 0 tractability; mandatory at
  Phase 3+ walk-forward evaluation. This separation is required to
  avoid silent leakage during Phase 3 model training.

**Non-monotone caveat** (NEW in v1, addresses A8/B9): The greedy
post-event rule is **not monotone in event additions**. Empirical:
adding STEO (2nd Tuesday) to a WPSR (Wednesday) baseline produces
zero net N gain (STEO replaces WPSR 1:1); adding STEO on top of
WPSR + FOMC reduces N from 207 to 198 because STEO's 10-day cooldown
sometimes blocks already-retained FOMC events. **Mandatory pre-screen
before any new family is registered:** run the harness with and
without the candidate family on the same configuration and reject the
addition if N strictly decreases.

## 6. Autocorrelation and Block Effective N (amended per A1, A6, A7)

```
N_eff_hac = N / (1 + 2 * sum_{k=1..K} max(0, rho_k))    # ← capped at 0
```

where:

- `rho_k` = lag-k autocorrelation of the validation score series
  (model residual or per-event skill score), capped at 0 (per A6).
  Cap follows the conservative reading that mean-reverting score
  series should not inflate N.
- `K` = `max(ceil((h + b) / event_spacing), 4)` (Newey-West auto rule).

**Phase 0 disposition (NEW per A7):** At Phase 0 there is no
validation score series — no model has been fit — so `N_eff_hac`
**cannot** be computed on residuals. The harness instead computes
HAC on the **raw target series** and reports it in
`n_hac_or_block_adjusted_by_target` as a Phase-3-readiness
diagnostic. **`n_star` at Phase 0 equals `N_after_purge_embargo` and
does NOT incorporate the raw-target HAC value.** From Phase 3
onward, `N_eff_hac` is computed on the validated model's per-event
skill score or residual series and propagates into `n_star` per the
formula above.

If autocorrelation estimates are unstable because N is small, use
circular block bootstrap with block length:

```
block_length >= ceil((horizon_days + embargo_days) / median_event_spacing_days)
```

Harness v1.0 uses `max(spec_lower_bound, 5)` to ensure the bootstrap
captures weekly cycles. Block-length sensitivity is documented in
the dependence analysis at
`docs/v2/dependence_analysis_3d_horizon.md`.

## 7. Power Targets (amended per A4)

The v0 power tables remain valid for the locked `WTI_FRONT_5D_*`
targets. **Per A4**, the harness now reports the directional MDE
both **against the observed positive rate** (v0 behaviour) AND
**against the naive 0.50 baseline**. The optical-overfit shift at
v0 N = 163 is small (≤ 0.5 pp) but should be reported transparently.

## 8. Model Complexity Constraints (unchanged from v0)

## 9. Phase Gates (unchanged from v0; amended per A7)

Phase gates are computed against `N_eff_oos_post2020`. Per A7,
`N_eff` at Phase 0 = `N_after_purge_embargo` (no HAC). At Phase 3+,
`N_eff` = `min(N_after_purge_embargo, N_eff_hac on residuals)`. The
Phase 0 gate decisions therefore mirror v0:

- N_star < 100  → stop
- 100 ≤ N < 250 → continue small-model only; no Phase 4
- 250 ≤ N < 500 → candidate audit allowed; constrained model search
- 500 ≤ N < 1000 → useful small-model research
- N ≥ 1000 → foundation-model revisit becomes statistically discussable

## 10. Current Interpretation

The 5d-horizon (locked v0) result against the post-rebuild PIT
store is unchanged: `N_star = 163`, rule
`continue_small_model_only`. The v1 harness reproduces this exactly
when invoked with `--families wpsr --horizon-days 5 --purge-days 5
--embargo-days 5`.

The v1 harness running on `wpsr + fomc + opec_ministerial` with the
same 5d regime produces `N_star = 209` — still
`continue_small_model_only`. **Phase 3 entry (≥ 250) is structurally
infeasible at the 5d horizon under free public post-2020 data**,
even after Tier 1.A event-family additions. This is a formal
finding of the v1 harness build.

The 3d horizon variant (§13 below) clears Phase 3 entry for
directional targets.

## 11. How N May Be Increased Without Cheating (amended per A5)

Permitted (unchanged from v0):

1. Extend pre-2020 first-release WPSR history; report pre-2020 and
   post-2020 separately.
2. Use CL front futures daily history for candidate audit targets.
3. Add genuinely distinct event families with their own PIT source
   contract and target definition (subject to the §5 additive-N
   pre-screen, A8).
4. Reduce purge or embargo only with a written dependence analysis
   and a versioned gate change. **The 3d horizon variant in §13 is
   the v1.0 example of this path.**
5. Use daily targets only if repeated weekly feature exposure is
   corrected by HAC/block effective N **and a stale-feature rejection
   policy** (NEW per A5):
   - Define `feature_age_days = (decision_ts − feature_release_ts) /
     86400`.
   - Reject events where `feature_age_days > stale_window_days` for
     any required feature.
   - `stale_window_days` defaults to `ceil(horizon_days * 1.5)`
     unless the feature's calendar YAML overrides it.

Forbidden (unchanged from v0).

## 12. Mandatory Manifest Fields (amended per A1)

The v1 harness output (`tractability.v1.0` schema) emits every v0
mandatory field plus:

- `n_hac_or_block_adjusted_by_target` (with Newey-West and circular
  block bootstrap point estimates and a Phase-0 disposition note)
- `vintage_quality_distribution` (top-level)
- `n_star_strict_hac_phase3plus` (per-target diagnostic for the
  Phase-3+ reading)
- `parameters.alpha_family`, `parameters.alpha_per_test`,
  `parameters.search_budget_runs`,
  `parameters.admissible_vintage_qualities`

If any v0 mandatory field is absent, the run is not valid evidence.
Harness v1.0 produces a complete manifest by construction.

## 13. Horizon variants (NEW per A9)

### 13.1 `WTI_FRONT_3D_LOG_RETURN` variant

Added to the target registry at `contracts/target_variables.py` as
a v1.x revision. Companion target name:
`WTI_FRONT_3D_RETURN_SIGN` (binary directional).

**Parameters:**
- `horizon_days = 3`
- `purge_days = 3`
- `embargo_days = 3`
- `cooldown = purge + embargo = 6 days < 7 days weekly cycle`

**Justification (per spec §11 #4):** the dependence analysis at
`docs/v2/dependence_analysis_3d_horizon.md` provides the written
analysis required by §11 #4 for any reduction in `purge` or
`embargo`. Key empirical findings:

- Post-thinning N at 3d horizon: **365** (was 163 at 5d for WPSR
  alone; 207 at 5d for WPSR + FOMC; 209 at 5d for WPSR + FOMC +
  OPEC).
- Newey-West HAC effective N at 3d (raw target, Phase 0
  diagnostic):
  - `return_sign`: 268 (clears Phase 3)
  - `return_3d` signed: 274 (clears Phase 3)
  - `return_3d` magnitude: 133 (**fails Phase 3** — magnitude not
    admitted at 3d)
- ρ₁ on returns/signs ≈ +0.20 (positive, as expected for momentum);
  ρ₂ within IID null; ρ₃ near the negative tail of the IID null,
  flagged for re-measurement at next backfill.

### 13.2 Admission rule for the 3d variant

`WTI_FRONT_3D_RETURN_SIGN` and `WTI_FRONT_3D_LOG_RETURN` (signed
continuous) are admitted to the target registry under the v1 spec.
`WTI_FRONT_3D_RETURN_MAGNITUDE` is **not** admitted because its HAC
effective N (133) falls below the Phase 3 floor.

### 13.3 Per-target MDE table at the 3d horizon

For `WTI_FRONT_3D_RETURN_SIGN` (n=268 effective at Phase 3
admission):

| Power scenario | Detectable sign lift |
|---|---:|
| Single pre-registered test, α=0.05, power=0.80 | ~ 8.4 pp |
| 12-run search budget, Bonferroni α/12 | ~ 11.1 pp |

For `WTI_FRONT_3D_LOG_RETURN` (signed) at n=274:

| Power scenario | Detectable raw effect (log return) |
|---|---:|
| Single pre-registered test | ~ 0.0049 |
| 12-run search budget | ~ 0.0064 |

(MDE numbers above use the v0 power formula evaluated at the
post-Phase-3-admission HAC-adjusted N. The harness emits both the
pre-HAC and post-HAC MDE; the table above quotes the more
conservative post-HAC value.)

### 13.4 Forbidden uses (3d variant)

- `WTI_FRONT_3D_RETURN_MAGNITUDE` is registered as a research
  diagnostic only and **MUST NOT** be used for Phase 3 candidate
  audit, paper promotion, or live promotion.
- The 3d variant operates on the same DCOILWTICO spot proxy at
  Phase 0 and inherits all v0 forbidden uses for spot
  (`executable_futures_replay`, `CL_front_month_backtest`,
  `MCL_execution_replay`).

### 13.5 Re-measurement schedule

The dependence analysis is valid until any of the following:

- A new event family is admitted (re-run §13 measurements
  end-to-end).
- The PIT manifest revision count exceeds 1% of total rows
  (currently 0%).
- Phase 3 produces an actual model residual series — at that point
  spec §6 propagates HAC into n_star and the 3d admission must be
  re-validated against residual autocorrelation, not raw target.

## Appendix: relationship to v0

This v1 spec is the working specification for the data-acquisition
plan at `~/.claude/plans/review-this-specification-develop-hidden-spring.md`
and the v1 tractability harness at `feasibility/tractability_v1.py`.
v0 remains the locked record of the post-rebuild Phase 0.3
verdict. The two specs diverge **only** in the eight clarifications
(A1-A9) listed in §0; the verdict at v0 parameters is byte-identical
under v1 execution.
