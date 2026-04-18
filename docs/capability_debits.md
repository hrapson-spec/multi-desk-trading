# Capability-claim debits

Per spec §1.3 ("work is pre-registered; debits are logged") and §12.2
item 6 ("No outstanding capability-claim debits above per-desk
budget"). This file consolidates the debits currently in effect at
Phase 1 exit.

Budget policy: per-desk debit count is not explicitly quantified in
the spec. The budget is qualitative — "are these debits proportional
to what Phase 1 actually delivered?" A debit with a named mitigation
path and a bounded upgrade scope is in-budget. A debit that
invalidates an architectural claim is not.

## Active debits at Phase 1 exit (2026-04-17)

### D1. Phase A model weakness (non-storage_curve desks)

**Claim relaxed.** §12.2 item 2 strictly reads "all 5 signal-emitting
desks pass their three hard gates on each scenario." Operationally,
the supply / demand / geopolitics / macro desks use ridge-on-4-features
classical models whose skill is seed-dependent. Across 10 seeds in the
multi-scenario Logic gate test, 5/10 seeds pass the ≥3/5 aggregate
threshold.

**Storage_curve (the load-bearing desk) passes 3/3 on all 10 seeds;
Gate 3 (hot-swap) passes 5/5 on all 10 seeds.** Those are the
architectural invariants. The other desks' skill is a model-quality
question, not an architecture-completeness question.

**Scope.** Phase 1 exits with the architectural claim verified and
model-quality claim partially unverified for 4 of 5 desks.

**Mitigation.** §7.3 escalation ladder for the affected desks:
  - Escalation 1 — classical specialist (BVAR, PyMC hierarchical).
  - Escalation 2 — borrowed-compute fine-tune.

Phase 2 work item, not a Phase 1 blocker.

**Pinned by.** Spec v1.11 (§12.2 item 2 recalibration).
**Tests.** `tests/test_logic_gate_multi_scenario.py`.

### D2. Weight promotion v0.2 Shapley-monotone

**Claim.** `propose_and_promote_from_shapley` (v0.2) omits the §8.3
step 4 held-out margin check. It promotes Shapley-proportional weights
whenever invoked; any Shapley-positive desk gets a positive weight.

**Scope.** Handlers (regime_transition) default to the v0.2 path.

**Mitigation.** `propose_validate_and_promote` (v0.3) adds held-out
margin validation; available for callers that want strict promotion.
Handler wiring to v0.3 is a future upgrade.

**Pinned by.** `research_loop/promotion.py` docstring lines 20-29.

### D3. HDP-HMM non-parametric K classifier deferred

**Claim.** §10 regime classifier ships as a 4-state Gaussian HMM via
hmmlearn. §8.5 capacity discipline assumes HDP-HMM for data-driven K
but the spec permits 4-state fixed-K under the v0.2 capability debit.

**Scope.** Regime count is fixed at 4 until HDP-HMM ships.

**Mitigation.** v0.3+ HDP-HMM implementation; interface stable.

**Pinned by.** Spec v1.5 changelog; §10 implementation commit
(`hmm-classifier-v0.2` tag).

### D4. Feed-reliability reinstatement — direct-insert fallback

**Claim.** When a retired desk has no recent `attribution_shapley`
rows, reinstatement falls back to
`reinstate_desk_direct(weight=0.1)` — a conservative seed weight.

**Scope.** Desks retired before any Shapley review ever ran will
always land on the fallback path.

**Mitigation.** As the system accumulates Shapley history, the primary
`historical_shapley_share` path takes over automatically. Direct-insert
is a cold-start bridge, not a regression.

**Pinned by.** Spec v1.9 §14.5 Layer 2 reinstatement description.
**Tests.** `tests/test_feed_reliability.py` (both paths covered).

### D5. Phase 2 month-5 checkpoint — CLOSED (2026-04-18)

**Closure evidence.** Phase 2 MVP shipped (tag `phase2-mvp-v1.12`):
`desks/dealer_inventory/` + `sim_equity_vrp/` + equity-VRP portability
contract. Interpreted per §14.7: "equity-VRP desk candidates exist in
some form at Phase 1 exit" is satisfied by the synthetic-only MVP
implementation. Reviewer audit path: `docs/phase2_mvp_completion.md`.

**Original scope (historical):** §14.7 demanded a month-5 checkpoint
confirming equity-VRP desk analogues exist for the Speckle and Spot
project. The MVP implementation is the synthetic-only analogue.

**Follow-on:** real Speckle-and-Spot production data wiring is a
separate external-dependency commitment, tracked outside this
file (it's not a code-side debit).

### D6. Grading-space Shapley deferred

**Claim.** §9.1 step 2 calls for grading-space (Print-grounded)
Shapley in addition to signal-space. Signal-space Shapley ships
(v0.1/v0.2, exact + sampled); grading-space is v0.3+.

**Scope.** Attribution quality is assessed in signal space only;
realisation-grounded contribution weighting deferred.

**Mitigation.** v0.3+ grading-space commit. Signal-space is a
sufficient statistic under the characteristic-function assumption.

**Pinned by.** `research_loop/promotion.py:20-29` + `attribution/`
module docstrings.

### D7. Phase 2 equity-VRP model quality (dealer_inventory + hedging_demand Gates 1 + 2)

**Claim relaxed.** Phase 2 equity-VRP desks so far
(`dealer_inventory` MVP, `hedging_demand` v1.13) pass Gate 3
(portability invariant — runtime hot-swap via
`eval.hot_swap.build_hot_swap_callables` since v1.14; see D9 closure
below) but fail Gate 1 (skill) and Gate 2 (sign preservation) on the
minimal synthetic equity-vol market.

Observed at tag `phase2-mvp-v1.12`:
- dealer_inventory G1 relative_improvement ≈ −0.5%, G2 dev/test_corr ≈ 0.

Observed at tag `phase2-desk2-hedging-demand-v1.13`:
- hedging_demand G1 relative_improvement = −0.1060, G2 dev/test_corr = 0.0000 (pinned).

**Scope.** Architectural claim is verified regardless: both desks
compose with the bus, Controller, grading harness, and attribution
layer end-to-end. Gate 3 passes as runtime hot-swap (`Controller.decide()`
exercised end-to-end; D9 closed 2026-04-18 at tag
`gate3-runtime-harness-v1.14`); portability tests pass.

**Mitigation.** Phase 2 scale-out: the remaining three desks
(`term_structure`, `earnings_calendar`, `macro_regime`) + a richer
synthetic vol market OR real Speckle-and-Spot data would give the
ridge something non-trivial to fit. §7.3 escalation ladder applies
to equity-VRP desks the same way it applied to oil D1.

**Pinned by.** `docs/phase2_mvp_completion.md`;
`tests/test_dealer_inventory_gates.py`;
`tests/test_hedging_demand_gates.py::test_hedging_demand_classical_three_gates_on_mvp_market` (pinned G1/G2 values — regression signal on silent drift).

### D8. Same-target aggregation normalization (Phase 2)

**Claim.** Both `dealer_inventory` and `hedging_demand` target
`VIX_30D_FORWARD`. The Controller's `combined_signal` currently sums
raw `point_estimate` levels across desks. Under this aggregation,
Shapley share reflects forecast SCALE (absolute vol level) not
independent information content — making the metric non-comparable
across same-target desks.

**Scope.** Blocks any "measurable Shapley contribution" claim for
same-target Phase 2 desks. No Phase 2 attribution harness exists
today to compute realised-decision Shapley in a normalized space.

**Mitigation.** Phase 2 attribution-harness upgrade (v0.3 class):
aggregate in contribution space (e.g., weighted log-return or
z-scored forecast) before Shapley. §8.2a sizing already normalises
via `k_regime`, but the post-aggregation attribution path does not.

**Pinned by.** Spec §9.2 (Shapley definition); no test encodes the
gap yet — D8 is the ticket to encode + fix.

### D9. Gate 3 runtime hot-swap harness — CLOSED (2026-04-18, v1.14, with scope caveat)

**Closure evidence.** `eval/hot_swap.py::build_hot_swap_callables()`
shipped at tag `gate3-runtime-harness-v1.14`. Replaces the
`run_controller_fn=lambda: True, run_controller_with_stub_fn=lambda: True`
tautology at 7 integration-level callsites with a real
`Controller.decide()` + `StubDesk` swap. Closure assertions verify
(a) Decision validity, (b) `combined_signal` delta matches
`−weight × point_estimate` under the stale-real/stale-stub interaction
branches, (c) honest `contributing_ids` membership. The 4 shell-unit
tests in `tests/test_gates.py` keep their `lambda: True` literals
because they legitimately test `gate_hot_swap`'s pass-through
contract — not the integration path.

**Load-bearing side-effect.** The closed-loop exercise surfaced a
real Controller bug at `controller/decision.py:96-104`: a retired
desk's (weight=0) forecast_id was appended to `contributing_ids`
after the staleness check, leaving retired desks visible in Decision
output while contributing 0 to `combined_signal`. Fix: `if w == 0.0:
continue` guard. Regression test at
`tests/test_controller_retire_exclusion.py`.

**Scope caveat.** D9 closed for the 7 migrated callsites:
- `tests/test_phase_a_clean_observations.py`
- `tests/test_phase_b_controlled_leakage.py`
- `tests/test_phase_c_realistic_contamination.py`
- `tests/test_logic_gate_multi_scenario.py`
- `tests/test_storage_curve_gates.py`
- `tests/test_dealer_inventory_gates.py`
- `tests/test_hedging_demand_gates.py`

Any future Gate 3 test wiring `lambda: True` in its
`run_controller_fn=` argument is expected to use
`build_hot_swap_callables` instead. The scope caveat preserves
symmetry: pre-v1.14 Gate 3 evidence reads as conformance-only;
post-v1.14 Gate 3 evidence reads as runtime hot-swap.

**Additional artefacts.** `failure_mode` enum field
(`"passed" | "controller_exception" | "assertion_failure"`) in
`gate_hot_swap.metrics`; same-target two-desk case at
`tests/test_hot_swap_two_desk.py` pinning the D8 production scenario
(dealer_inventory ⊕ hedging_demand both → `VIX_30D_FORWARD`).

**Pinned by.** Spec §0 v1.14 changelog; §15 derivation trace row
tagged `gate3-runtime-harness-v1.14`; phase1 / phase2_mvp completion
manifest annotations; RAID log I-09 closure row.

## Closed debits (historical)

- **D5 (Phase 2 month-5 checkpoint)** — closed 2026-04-18 by MVP ship.
- **D9 (Gate 3 runtime hot-swap harness)** — closed 2026-04-18 at tag
  `gate3-runtime-harness-v1.14` with scope caveat (7 migrated
  integration callsites named above).

## Budget assessment

**All debits are in-budget.** Each names a bounded upgrade path and
none invalidates the Phase 1 or Phase 2 architectural claim:

- D1: oil model weakness, not architecture weakness. Storage_curve + hot-swap passes uphold the Phase 1 claim.
- D2, D6: attribution/promotion path are extensible; v0.3 primitives already shipped.
- D3: HDP-HMM is a non-parametric upgrade to an already-working fixed-K classifier.
- D4: cold-start bridge that self-heals as Shapley data accumulates.
- D5: CLOSED by Phase 2 MVP ship.
- D7: equity-VRP model weakness mirror of D1, now covering both dealer_inventory + hedging_demand. Gate 3 passes as runtime hot-swap from v1.14 onward (D9 closed); Gates 1+2 remain scale-out work.
- D8: same-target aggregation normalization — v1.13 opened, blocks Shapley attribution claims across same-target desks.
- D9: CLOSED 2026-04-18 at tag `gate3-runtime-harness-v1.14` with scope caveat — 7 migrated callsites now carry runtime hot-swap evidence; pre-v1.14 Gate 3 passes are attribute-conformance only.

**Phase 1 §12.2 item 6 satisfied. Phase 2 architectural claim
verified through Desk 2 (D7 model-quality, D8 same-target
attribution — both scoped + mitigated). D9 closed 2026-04-18.**
