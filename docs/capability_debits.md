# Capability-claim debits

Per spec §1.3 ("work is pre-registered; debits are logged") and §12.2
item 6 ("No outstanding capability-claim debits above per-desk
budget"). This file records the **current** debit state of the live
worktree.

Budget policy: per-desk debit count is qualitative, not numeric. A debit
is in-budget if it is bounded, explicitly mitigated, and does not break
the architectural claim. A debit that invalidates portability,
controller correctness, or the frozen contract surface is not in-budget.

## Active debits (2026-04-22 worktree — v1.16 restructure)

### D1. Phase A model weakness — v1.16 narrowed scope

**v1.16 scope narrowing (2026-04-22).** Roster shrinks from 5 oil desks to 3
(`storage_curve`, `supply_disruption_news`, `oil_demand_nowcast`). D1 now
covers only the two non-storage merged desks. Composite and inherited
classical heads are ridge-level; the full event-hurdle / mixed-frequency
nowcast rebuilds are §7.3 escalation items under the commissions at
`docs/pm/supply_disruption_news_engineering_commission.md` and
`docs/pm/oil_demand_nowcast_engineering_commission.md`.

Gate 2 (sign preservation) is the active capability gate under v1.16;
per-seed results show Gate 2 aggregate holds at 2-3/3 across the 10-seed
Logic-gate sweep, and the combined-pass threshold is ≥ 5/10 seeds. Gate 1
aggregate is tracked separately under D-16 (test-infrastructure debit).

### D1-historical. Phase A model weakness (v1.11–v1.15 context, superseded)

**Pre-v1.16 claim (preserved for audit trail).** The four non-storage
Phase A desks still use simple classical ridge specialists over compact
summary-feature surfaces. Their skill remains seed-dependent. Across
10 seeds in the multi-scenario Logic-gate sweep, **6/10** seeds pass
the ≥3/5 Gate 1 + Gate 2 aggregate.

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

### D7. Phase 2 equity-VRP model quality — v1.16 re-scoped

**v1.16 re-scoping (2026-04-22).** `dealer_inventory` + `hedging_demand`
merged into `surface_positioning_feedback` per the adopted pasted review
in `docs/first_principles_redesign.md`. Emission retargeted to
`VIX_30D_FORWARD_3D_DELTA` (signed 3-day delta) so the equity family is
unit-consistent under `controller/decision.py:94-112` raw-sum.
Directional score is now the fitted delta head (replaces the legacy
dealer_inventory heuristic `flow_last + 0.25 * vega_normalized`). D7 now
covers Gate 2 on the merged-channels composite ridge; full monotone-GAM /
GBDT rebuild is the §7.3 escalation under the commission at
`docs/pm/surface_positioning_feedback_engineering_commission.md`.

`fair_vol_baseline` channel added at v1.16 C11 supports the
`next_session_rv_surprise` internal training signal; the composite ridge
does not yet consume it (Phase 2 scope).

### D7-historical. v1.13–v1.15 context (superseded)

**Pre-v1.16 claim (preserved for audit trail).** Both shipped equity-VRP
desks (`dealer_inventory`, `hedging_demand`) pass Gate 3 runtime hot-swap
and now clear Gate 1 on the pinned MVP slice, but **Gate 2 remains
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
- `tests/test_dealer_inventory_gates.py` (historical — v1.15-era)
- `tests/test_hedging_demand_gates.py` (historical — v1.15-era)
- `docs/phase2_mvp_completion.md` (historical manifest + v1.16 current status section)
- v1.16 state: `tests/test_surface_positioning_feedback_gates.py` **pending C12 follow-on wave** (see manifest §"Deferred to a post-C12 follow-on wave"). Until then Gate 2 on the composite ridge is measured via the logic-gate multi-scenario sweep; dedicated pinned regression values are re-recorded when the composite desk has its own gate file.

### D-16. Logic-gate Gate 1 baseline-unit mismatch (v1.16 test-infrastructure) — CLOSED 2026-04-22

**Opened 2026-04-22** at C7 ship; **closed 2026-04-22** at W9 ship; recorded in `docs/pm/raid_log.md` as decision D-16.

**Closure evidence.** `eval.data.zero_return_baseline` added as the random-walk analog for log-return targets. `tests/test_logic_gate_multi_scenario.py::_run_gates_for_desk` now picks the baseline per desk (`random_walk_price_baseline` for WTI_FRONT_MONTH_CLOSE, `zero_return_baseline` for WTI_FRONT_1W_LOG_RETURN). `_fit_and_drive` generates per-desk Prints keyed off the desk's emitted target (price value or log-return value). Gate 1 aggregate ≥ 2/3 restored in `_scenario_passes`. Post-closure: 6/10 seeds pass the full per-scenario threshold; per-seed Gate 1 counts 2-3/3. Confirms the original ship-time diagnosis that D-16 was a test-infrastructure debit, not a model-quality finding.

**Retained for audit trail:**


The v1.16 merged oil desks (`supply_disruption_news`, `oil_demand_nowcast`)
emit `WTI_FRONT_1W_LOG_RETURN`. The current `eval.data.random_walk_price_baseline`
and the Print generator in `tests/test_logic_gate_multi_scenario.py` both
operate in price-level units (designed for the pre-v1.16 5-desk era when
oil desks emitted `WTI_FRONT_MONTH_CLOSE`). Gate 1 compares the desk's
point_estimate to the baseline's prediction — scale-incompatible when one
is a log-return and the other is a price. Gate 1 always fails for the
merged desks under the current test infrastructure.

**Scope.** Test-infrastructure debit, not a model-quality finding. Gate 2
(sign preservation) is unaffected — `_fit_and_drive` already converts
scores and outcomes to log-return space before splitting.

**Workaround (C7 ship).** `_scenario_passes` drops the Gate 1 aggregate
requirement from the combined-pass criterion. Gate 1 is still evaluated
per-desk and reported in diagnostics; only the aggregate threshold was
relaxed. Strict invariants (storage_curve 3/3 + Gate 3 3/3) and Gate 2
aggregate ≥ 2/3 remain load-bearing.

**Mitigation path.** Rebuild `eval.data.random_walk_price_baseline` and
the Print-generation path around log-return grading; scoped to the
post-C12 follow-on wave that also migrates ~27 test imports and deletes
the 6 committed legacy desk directories.

**Pinned by.**
- `tests/test_logic_gate_multi_scenario.py::_scenario_passes` docstring
- `docs/pm/raid_log.md::D-16`

### D-17. earnings_calendar Gate 1/2 weak — pending earnings-event channel

**Opened 2026-04-22** at W10 ship. The `earnings_calendar` desk ships as a structurally-complete skeleton that satisfies DeskProtocol, Gate 3 hot-swap, and raw-sum composition with `surface_positioning_feedback`. Its ridge classical head reads only vol-level proxies because the sim has no earnings-event channel (per-ticker scheduled release dates, cluster size, sector weight). Gate 1/2 skill is expected weak until the full earnings-event mechanism lands.

**Scope.** Follow-on wave per commission §5 at `docs/pm/earnings_calendar_engineering_commission.md`. Requires:
- earnings-event channel in `sim_equity_vrp/` (scheduled release dates, clusters, sector weights)
- structured event-schema model (class + state conditioning)
- calibrated impact distribution

**Mitigation.** Phase 2 done-criterion ("2 equity desks pass Gate 3; ≥ 1/2 pass Gates 1+2 aggregate") is still met because `surface_positioning_feedback` is the load-bearing equity desk for Gate 1/2 under v1.16; `earnings_calendar` carries the architectural two-desk + same-target invariant. D-17 is in-budget per the §12.2 capability-claim policy.

**Pinned by.**
- `tests/test_earnings_calendar_skeleton.py` (Gate 3 + compositional invariants pass)
- `desks/earnings_calendar/spec.md` (documents the skeleton scope)
- `docs/pm/earnings_calendar_engineering_commission.md` (§5 follow-on scope)

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
