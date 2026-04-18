# Capability-claim debits

Per spec §1.3 ("work is pre-registered; debits are logged") and §12.2
item 6 ("No outstanding capability-claim debits above per-desk
budget"). This file records the **current** debit state of the live
worktree.

Budget policy: per-desk debit count is qualitative, not numeric. A debit
is in-budget if it is bounded, explicitly mitigated, and does not break
the architectural claim. A debit that invalidates portability,
controller correctness, or the frozen contract surface is not in-budget.

## Active debits (2026-04-18 current worktree)

### D1. Phase A model weakness (non-storage_curve desks)

**Claim relaxed.** The four non-storage Phase A desks still use simple
classical ridge specialists over compact summary-feature surfaces. Their
skill remains seed-dependent. Across 10 seeds in the multi-scenario
Logic-gate sweep, **6/10** seeds now pass the ≥3/5 Gate 1 + Gate 2
aggregate.

**Storage_curve (the load-bearing desk) still passes 3/3 on all 10
seeds; Gate 3 (hot-swap) still passes 5/5 on all 10 seeds.** Those are
the architectural invariants. The residual weakness is model quality,
not architecture completeness.

**Scope.** Phase 1 exits with the architecture verified and model
quality still only partially verified for supply / demand /
geopolitics / macro.

**Mitigation.** §7.3 escalation ladder for the affected desks:
- Escalation 1 — stronger classical specialist (BVAR / PyMC
  hierarchical).
- Escalation 2 — borrowed-compute fine-tune.

**Pinned by.** `tests/test_logic_gate_multi_scenario.py` and spec v1.11
(historical) plus v1.15 changelog note (current narrowing to 6/10).

### D7. Phase 2 equity-VRP model quality (Gate 2 sign preservation remains open)

**Claim relaxed.** Both shipped equity-VRP desks
(`dealer_inventory`, `hedging_demand`) pass Gate 3 runtime hot-swap and
now clear Gate 1 on the pinned MVP slice, but **Gate 2 remains
unstable** on the minimal synthetic equity-vol market.

Current pinned regression values:
- `dealer_inventory`: Gate 1 `relative_improvement = +0.0424`; Gate 2
  `dev_rho = -0.0109`, `test_rho = +0.0456`
- `hedging_demand`: Gate 1 `relative_improvement = +0.0356`; Gate 2
  `dev_rho = +0.2155`, `test_rho = -0.1403`

**Root cause narrowed.** The original Phase 2 weakness combined
train/serve mismatch, weak direct metric wiring, and underpowered
summary-feature heads. The current worktree fixes the train/serve path
(observed channels, not latent), fixes the metric-key bug, and upgrades
both desk models to direct vol-delta heads with richer feature sets.
That closes the Gate 1 weakness on the pinned slice, but the sign
relationship still fails to hold dev → test.

**Scope.** The architectural claim remains verified regardless: both
desks compose with the bus, Controller, grading harness, attribution
layer, and Gate 3 runtime harness end-to-end.

**Mitigation.** Phase 2 scale-out:
- Add the remaining desks (`term_structure`, `earnings_calendar`,
  `macro_regime`) to enrich the equity-VRP feature surface.
- Strengthen the synthetic market or wire real Speckle-and-Spot data.
- Use the same §7.3 escalation ladder if Gate 2 remains unstable.

**Pinned by.**
- `tests/test_dealer_inventory_gates.py`
- `tests/test_hedging_demand_gates.py`
- `docs/phase2_mvp_completion.md` (historical manifest + current note)

## Closed debits (historical)

### D2. Weight promotion v0.2 Shapley-monotone — CLOSED (2026-04-18)

**Closure evidence.** The active research-loop promotion path is now
v0.3, not the old v0.2 default. `research_loop.handlers.regime_transition_handler`
computes grading-space Shapley and calls
`propose_validate_and_promote(...)`, which enforces the held-out margin
check before promotion. `propose_weights_from_shapley(...)` also now
uses the positive part of Shapley instead of raw absolute magnitude, so
harmed desks do not retain positive candidate weight.

**Residual legacy surface.** The v0.2 helper remains in the module for
historical artefacts and narrow callers, but it is no longer the default
handler path.

**Pinned by.**
- `tests/test_weight_promotion.py`
- `tests/test_regime_transition.py`
- `tests/test_research_loop.py`

### D3. HDP-HMM non-parametric K classifier deferred — CLOSED (2026-04-18)

**Closure evidence.** The shipped `HMMRegimeClassifier` no longer fixes
`K=4`. The default path now selects `K ∈ [2, 6]` by BIC over bounded
Gaussian-HMM candidates, while preserving the same `RegimeLabel`
contract and opaque `hmm_regime_*` identifier family.

**Important precision.** Full Bayesian HDP-HMM remains a future model
family option, but the live capability debit was the **fixed-K
weakness**, and that is now closed.

**Pinned by.**
- `desks/regime_classifier/classical.py`
- `tests/test_hmm_classifier.py`

### D4. Feed-reliability reinstatement — direct-insert fallback — CLOSED (2026-04-18)

**Closure evidence.** Reinstatement no longer jumps directly from
`historical_shapley_share(...)` to `reinstate_desk_direct(weight=0.1)`.
The live hierarchy is:
1. `historical_shapley_share(...)`
2. `latest_nonzero_weight_for_desk(...)`
3. direct conservative seed weight

That means a desk with no recent Shapley rows but a valid historical
weight no longer collapses to the blunt `0.1` fallback. The residual
direct insert is now only the true cold-start case.

**Pinned by.**
- `tests/test_feed_reliability.py`
- `research_loop/feed_reliability.py`
- `research_loop/handlers.py`

### D5. Phase 2 month-5 checkpoint — CLOSED (2026-04-18)

**Closure evidence.** Phase 2 MVP shipped at tag `phase2-mvp-v1.12`:
`desks/dealer_inventory/` + `sim_equity_vrp/` + equity-VRP portability
contract. Per §14.7, the synthetic-only analogue is sufficient evidence
that equity-VRP desk candidates exist in some form.

### D6. Grading-space Shapley deferred — CLOSED (2026-04-18)

**Closure evidence.** `attribution.compute_shapley_grading_space(...)`
is now shipped and used by the active research-loop handlers when Prints
are available. The promotion path is no longer signal-space-only.

**Pinned by.**
- `tests/test_attribution_shapley.py`
- `tests/test_regime_transition.py`
- `research_loop/handlers.py`

### D8. Same-target attribution normalization (Phase 2) — CLOSED (2026-04-18)

**Closure evidence.** Same-target desks are now compared in normalized
contribution space inside grading-space Shapley. The grading path
z-scores the forecast surface and realised-print surface over the review
window before coalition evaluation, so same-target desks are not
credited merely for operating at a larger raw vol-level scale.

**Important precision.** The Controller's live decision rule still sums
raw point estimates by design; the closed debit is the **attribution
fairness gap**, not a claim that sizing semantics changed.

**Pinned by.**
- `tests/test_attribution_shapley.py::test_grading_space_same_target_scale_neutrality`
- `tests/test_attribution_shapley.py::test_grading_space_prefers_information_over_scale`
- `tests/test_hot_swap_two_desk.py`

### D9. Gate 3 runtime hot-swap harness — CLOSED (2026-04-18, v1.14, with scope caveat)

**Closure evidence.** `eval.hot_swap.build_hot_swap_callables()` replaced
the integration-level `lambda: True` tautology at the migrated Gate 3
callsites with a real `Controller.decide()` + `StubDesk` swap.
Assertions cover:
- Decision validity
- expected `combined_signal` delta
- honest `contributing_ids` membership

The closed-loop exercise also surfaced and fixed a real Controller bug:
retired desks (weight 0) no longer leak into `contributing_ids`.

**Scope caveat.** D9 is closed for the migrated integration callsites;
the shell-unit tests in `tests/test_gates.py` keep literal callables
because they test the gate shell contract itself, not the integration
path.

## Budget assessment

**The remaining open debits are in-budget.**

- D1 remains a bounded model-quality debit. The strict architectural
  invariants still hold on 10/10 Logic-gate seeds.
- D7 remains a bounded model-quality debit. Gate 3 runtime hot-swap is
  verified; the residual issue is sign stability on the minimal
  synthetic market, not portability or controller correctness.

**The previously open architectural / attribution / promotion debits are
now closed.**

- D2 closed: validated promotion is the active path.
- D3 closed: the regime classifier is no longer fixed-K.
- D4 closed: reinstatement now uses a proper fallback hierarchy.
- D5 closed: Phase 2 MVP shipped.
- D6 closed: grading-space Shapley shipped.
- D8 closed: same-target attribution fairness is normalized.
- D9 closed: runtime hot-swap harness shipped.

**Current project state.**

- Phase 1 architectural claim remains verified.
- Phase 2 portability claim remains verified.
- Open work is now concentrated in model quality, not infrastructure.
