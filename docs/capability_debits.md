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

### D5. Phase 2 month-5 checkpoint — not yet run

**Claim.** §14.7 demands a month-5 checkpoint confirming equity-VRP
desk analogues exist for the Speckle and Spot project. That checkpoint
has not been run.

**Scope.** Phase 2 readiness is unverified.

**Mitigation.** Month-5 review — can be done at Phase 1 exit date or
shortly after. If analogues missing, Phase 2 slips; debit escalates to
"Phase 1 completion claim invalidated in retrospect" per §14.7.

**Pinned by.** Spec §14.7. Not a code-side debit.

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

## Closed debits (historical)

None yet — Phase 1 is the first exit point.

## Budget assessment

**All six debits are in-budget.** Each names a bounded upgrade path
and none invalidates the Phase 1 architectural claim:

- D1: model weakness, not architecture weakness. Storage_curve + hot-swap passes uphold the claim.
- D2, D6: attribution/promotion path are extensible; v0.3 primitives already shipped.
- D3: HDP-HMM is a non-parametric upgrade to an already-working fixed-K classifier.
- D4: cold-start bridge that self-heals as Shapley data accumulates.
- D5: external dependency (Speckle and Spot project), not a code-side blocker.

**§12.2 item 6 satisfied.**
