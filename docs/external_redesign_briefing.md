# External Redesign Briefing

**Project:** multi-desk-trading  
**Audience:** external expert reviewing underperforming desks from first principles  
**Prepared from:** `docs/architecture_spec_v1.md`, PM artefacts, completion manifests, capability debits, desk specs, and gate tests  
**Date context:** current worktree as of 2026-04-22

## 1. Executive summary

This repository is an **architecture-first** systematic trading research project. The core deliverable is not a P&L number; it is a reusable multi-desk architecture that can be redeployed across domains with **zero shared-infrastructure changes**.

That architectural claim is currently in good shape:

- Phase 1 (oil-domain architecture build) is complete.
- Phase 2 MVP (equity-VRP redeployment with one desk) is complete.
- Phase 2 Desk 2 (`hedging_demand`) is shipped.
- Gate 3 hot-swap is now a **real runtime Controller test**, not a tautology.
- Shared infra remains portable across oil and equity-VRP.

The weak point is now concentrated in **desk design / observability / model quality**, not in the shared architecture:

- Oil desks still carry **D1**: non-`storage_curve` desks remain weak and seed-dependent.
- Equity-VRP desks still carry **D7**: Gate 1 is now positive on the pinned MVP slice, but **Gate 2 sign preservation remains unstable**.

The redesign question is therefore not "how do we fix the controller/bus/contracts?" but:

1. Are the underperforming desks well-defined in the first place?
2. Do the current simulator and observation layers encode the intended mechanisms strongly enough for any model to succeed?
3. Should some desks be re-scoped, split, merged, renamed, or removed?

## 2. What the project is trying to prove

The project aims to prove that a multi-desk trading research architecture can:

- express desk forecasts through a stable contract surface,
- combine them through a regime-aware controller,
- grade them against realised outcomes,
- attribute contribution across desks,
- run a research loop that can adjust or retire desks,
- and then redeploy the same shared machinery to an unrelated asset class.

The success criterion is architectural portability, not immediate model excellence.

## 3. What is frozen vs what is redesignable

### Treated as frozen unless a strong argument proves otherwise

- `contracts/`
- `controller/`
- `bus/`
- `persistence/`
- `eval/`
- `provenance/`
- `scheduler/`
- the portability claim itself
- Gate 3 hot-swap semantics

### Open to redesign

- desk definitions
- desk boundaries
- desk targets
- desk horizons
- observation channels
- simulator structure
- model family
- training labels
- feature construction
- whether a desk should exist at all in its current form

## 4. Current shipped state

### Completed milestones

- **Phase 1 complete** on 2026-04-17.
- **Phase 2 MVP complete** on 2026-04-18.
- **Phase 2 Desk 2 `hedging_demand`** shipped on 2026-04-18.
- **D9 Gate 3 runtime harness** closed on 2026-04-18.

### Current phase

The project is in **Phase 2 scale-out**. The next planned desks are:

- `term_structure`
- `earnings_calendar`
- `macro_regime`

### Important project status distinction

- **Architecture:** verified strongly enough to proceed.
- **Model quality:** still materially open.

## 5. Gate semantics

Every desk is evaluated against three hard gates:

### Gate 1

**Skill vs pre-registered naive baseline.**

This is a capability claim. A desk should beat its naive baseline on held-out data.

### Gate 2

**Dev-to-test sign preservation.**

This is also a capability claim. The directional relationship the desk claims should preserve sign from dev to test.

### Gate 3

**Hot-swap against a stub.**

This is the strict architectural invariant. From v1.14 onward, Gate 3 uses a real runtime harness that exercises `Controller.decide()` with a real desk and a stub swap.

Interpretation:

- Gate 3 failure is an architecture failure.
- Gate 1/2 failure is a desk-model / desk-definition / observability failure.

## 6. What is working well

### Shared architecture

The project has working implementations for:

- contracts
- controller and cold-start behavior
- attribution
- research-loop handlers
- persistence
- replay determinism
- grading harness
- portability tests
- soak / reliability infrastructure

### Runtime hot-swap evidence

Before v1.14, integration Gate 3 callsites used `lambda: True`, which made the pass signal tautological. That is now fixed. Gate 3 evidence from v1.14 onward reflects actual Controller execution.

### Research-loop / attribution improvements in the current worktree

The current worktree also includes:

- normalized grading-space Shapley,
- validated promotion path,
- historical-weight reinstatement fallback,
- adaptive-K Gaussian HMM regime classifier.

These changes strengthen attribution and research-loop behavior, but they do **not** close the remaining desk-quality debits.

## 7. Where the project is weak

## 7.1 Oil desks: D1 remains open

The oil Phase A logic-gate aggregate improved from `5/10` to `6/10` seeds, but the non-`storage_curve` desks remain weak.

Current status:

- `storage_curve` is the load-bearing oil desk and still passes its strict invariants.
- Gate 3 passes for all five desks on all ten logic-gate seeds.
- The remaining four desks are still model-quality weak:
  - `supply`
  - `demand`
  - `geopolitics`
  - `macro`

Interpretation:

- The architecture is not the blocker.
- The likely bottleneck is some combination of:
  - weak desk definition,
  - weak simulator structure,
  - weak observation design,
  - underpowered model family.

## 7.2 Equity-VRP desks: D7 remains open

The two shipped equity-VRP desks are:

- `dealer_inventory`
- `hedging_demand`

Current pinned regression values:

- `dealer_inventory`
  - Gate 1 `relative_improvement = +0.0424`
  - Gate 2 `dev_rho = -0.0109`
  - Gate 2 `test_rho = +0.0456`
- `hedging_demand`
  - Gate 1 `relative_improvement = +0.0356`
  - Gate 2 `dev_rho = +0.2155`
  - Gate 2 `test_rho = -0.1403`

Interpretation:

- Both desks now clear Gate 1 on the pinned MVP slice.
- Both desks still fail the more important stability question:
  **the directional relationship does not preserve cleanly from dev to test.**

This suggests that the residual problem is not "small model underfit" alone. It may reflect:

- a poor target/horizon choice,
- an observation layer that is too weak or too synthetic,
- desk decomposition that does not line up with the actual mechanism,
- or a mismatch between what Gate 2 is measuring and what the desk should really claim.

## 8. Desk-by-desk redesign targets

The underperforming desks that most need first-principles review are:

### Oil

- `supply`
- `demand`
- `geopolitics`
- `macro`

### Equity-VRP

- `dealer_inventory`
- `hedging_demand`

`storage_curve` should be treated as the current benchmark for a desk that is structurally load-bearing enough to survive the gate regime.

## 9. Core redesign questions for the external expert

For each underperforming desk, the expert should answer:

1. What mechanism is this desk actually trying to capture?
2. Is the current target variable the right one?
3. Is the current horizon the right one?
4. What observables legitimately identify this mechanism at decision time?
5. Does the simulator encode that mechanism strongly enough for learning to be possible?
6. Is the desk separable from adjacent desks, or is the decomposition itself wrong?
7. Should the problem be reframed as:
   - a level forecast,
   - a delta forecast,
   - a spread forecast,
   - an event model,
   - a regime-conditioned classifier,
   - or something else?
8. What failure mode best explains the current performance?
9. What is the minimum viable redesign?
10. What experiment would falsify that redesign quickly?

## 10. Current hypotheses worth challenging

The external reviewer should feel free to reject any of the following assumptions:

- that the current desk names reflect real separable mechanisms,
- that all desks should be direct point forecasters,
- that the current horizons are correct,
- that ridge-on-summary-features is even the right class of model,
- that the simulator currently contains enough structure for the weak desks to succeed,
- that every current desk deserves to survive into Phase 2 scale-out.

The strongest useful answer may be:

- split this desk,
- merge these two desks,
- rename the desk around the actual mechanism,
- or remove the desk entirely until the simulator/data layer justifies it.

## 11. Constraints the redesign must respect

- Shared infra portability should remain intact.
- Gate 3 must stay strict.
- Contracts should remain stable unless there is a compelling reason otherwise.
- The redesign should distinguish clearly between:
  - bad model,
  - bad desk definition,
  - bad simulator observability,
  - bad evaluation framing.

## 12. Suggested deliverables from the expert

Ask for a design memo, not code, with:

- one mechanism map per underperforming desk,
- one observability audit per desk,
- a proposed revised desk decomposition,
- target/horizon recommendations,
- model-family recommendations,
- required simulator or data changes,
- a minimal falsification experiment plan,
- a migration plan ranked by payoff vs implementation cost.

## 13. Important caveats

- `README.md` is stale and should not be treated as authoritative project status.
- The clean shipped baseline on `main` is earlier than some of the latest model/audit notes in the current worktree.
- The current worktree passes the full suite, but some of the latest improvements are not yet a cleanly split ship unit.

## 14. Recommended source packet

If the expert wants to read only a minimum source set, start here:

- `docs/architecture_spec_v1.md`
- `docs/capability_debits.md`
- `docs/pm/master_plan.md`
- `docs/phase1_completion.md`
- `docs/phase2_mvp_completion.md`
- `sim/observations.py`
- `sim_equity_vrp/observations.py`
- `eval/gates.py`
- `tests/test_logic_gate_multi_scenario.py`
- `tests/test_dealer_inventory_gates.py`
- `tests/test_hedging_demand_gates.py`
- the relevant `desks/*/spec.md`
- the relevant `desks/*/classical.py`

## 15. Bottom line

The project no longer has a convincing excuse to blame shared infrastructure for the weak desks.

The architecture is sufficiently mature. The redesign task should now be treated as a first-principles review of:

- desk decomposition,
- mechanism identifiability,
- observability,
- simulator realism,
- and evaluation framing.

That is the right level for an external expert review.
