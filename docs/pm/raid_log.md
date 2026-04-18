# RAID log

**Project**: multi-desk-trading architecture  
**Last updated**: 2026-04-18  
**Scope**: forward-looking. Defects/bugs belong in `problem_log.md`. Capability-claim debits belong in `capability_debits.md`. This file tracks **strategic** risks, assumptions, issues, and decisions.

Conventions:
- **ID format**: `R-nn` (risk), `A-nn` (assumption), `I-nn` (issue), `D-nn` (decision).
- **Status**: `open`, `monitoring`, `closed`.
- **Severity**: `high`, `medium`, `low` (risks + issues only).

---

## Risks

| ID | Risk | Severity | Likelihood | Mitigation | Owner | Status |
|---|---|---|---|---|---|---|
| R-01 | Phase 2 scale-out misses 2026-07-17 deadline (§14.6 realism flag: +1-2 weeks per escalation) | High | Medium | Reuse Phase 1 patterns aggressively; hold the four scale-out desks to ridge-only; escalate only if Gate 3 at risk | Henri | Open |
| R-02 | Speckle-and-Spot project doesn't have real-data feeds when Phase 3 begins | High | Medium | Synthetic-only MVP already verifies the architectural claim; Phase 3 scope can slide if real data isn't ready | Henri | Monitoring |
| R-03 | Single-operator bus factor. All architectural context lives in one head + this repo | High | Always | Documentation discipline: spec + manifests + RAID log stay current; tag everything; conversations archived | Henri | Monitoring |
| R-04 | Synthetic-data regime shift when real data is wired (Phase 3). Implicit assumptions about stationarity, feature availability, missingness break under real conditions | High | High | Staged observability already anticipates this (Phase B leakage + Phase C realistic contamination tests). Live-data validation is Phase 3's whole point | Henri | Monitoring |
| R-05 | LLM cost overrun (§6.4 budget: tens of dollars / month). Research-loop work scope creep would push it higher | Medium | Medium | Postcondition gate already enforces tier routing. Monthly cost review if API usage begins | Henri | Open |
| R-06 | 8GB compute constraint blocks a future escalation that requires fine-tuning | Medium | Low | §7.3 escalation ladder anticipates borrowed compute (Colab / cloud) for fine-tune; treat as capability debit not blocker | Henri | Monitoring |
| R-07 | Model-quality debits D1 + D7 compound if not addressed. A reviewer could argue architecture success doesn't compensate for 4/5 desks being weak | Medium | Medium | Explicitly framed in spec as "architecture vs. model-quality separation" (§1.3). Phase 2 scale-out + §7.3 escalations address this | Henri | Open |
| R-08 | Spec drift: 12 revisions in one session means the spec could lose coherence. Future sections may contradict old ones | Medium | Low | §0 changelog + §15 derivation trace + capability_debits.md cross-reference. Any reader can reconstruct the decision trail | Henri | Monitoring |
| R-09 | Test suite growth vs. CI time. 377 tests; full run ~24s now. If Phase 2 scale-out adds 10-seed multi-scenario tests per desk, full run could reach minutes | Low | Medium | Mark slow tests explicitly; keep pytest default fast; long runs opt-in via markers | Henri | Open |
| R-10 | Reliability-gate 4h run may expose failure modes not caught by instrumentation. An undetected OS-level issue (permission, FS quirk) could surface on first run | Low | Low | Numeric thresholds are pre-registered; checkpoint-resume means a failure is recoverable; non-incident Interrupts don't reset the clock | Henri | Open |

## Assumptions

| ID | Assumption | Why it holds | What breaks if it doesn't | Status |
|---|---|---|---|---|
| A-01 | Synthetic data is sufficient for Phase 1 + Phase 2 MVP architectural claim | Spec §1.2 + §12.2 explicitly frame Phase 1 as synthetic | Phase 1 + Phase 2 MVP completion manifests are invalidated if strict interpretation demands real data | Open |
| A-02 | Ridge-on-classical-features models are good enough for architecture validation (model-quality is a separate claim, logged as debits D1, D7) | Spec §7.3 frames escalations as opt-in under gate failures | Auditor could require 5/5 per scenario; forces Phase 2 scale-out to include escalations | Open |
| A-03 | 3-month Phase 2 deadline is meaningful (as opposed to aspirational) | Spec §12.2: "Longer delay drifts the architecture and invalidates the test" | Missed deadline becomes a capability-claim debit; Phase 1 "done" claim retroactively questioned | Open |
| A-04 | Sole operator remains Henri for Phase 2 + Phase 3 | User's working style + project scope | Bus factor materialises if Henri unavailable; documentation must suffice for handover | Open |
| A-05 | Speckle-and-Spot project has equity-VRP desk analogues that map to the 5-desk decomposition (supply/demand/curve/events/macro) | §14.7 spec text + user's earlier statements about the target project | Phase 2 deadline slips; D5 reopens | Monitoring |
| A-06 | 4h Reliability gate soak catches the meaningful failure modes | §14.9 v1.10 calibration — derived from failure-mode exposure table | A multi-day leak pattern goes undetected; surfaces later under Phase 3 real-data run | Open |
| A-07 | Capability-debit budget is qualitative ("proportional to what was delivered"), not quantified | Spec §12.2 item 6 wording; capability_debits.md closing assessment | Reviewer applies strict quantitative reading; some debits forced to close before Phase 2 exit | Open |
| A-08 | Git tags + commit messages are the audit trail. No formal documentation beyond spec + manifests + this file | Solo-operator context; Git history is durable | If external audit requires formal records, retroactive documentation needed | Open |

## Issues

| ID | Issue | Severity | Opened | Owner | Status | Notes |
|---|---|---|---|---|---|---|
| I-01 | 4h Reliability gate soak not yet executed (§12.2 item 3 operator-side step) | Medium | 2026-04-17 | Henri | Open | Phase 1 code-complete; this is the one remaining code-external step |
| I-02 | D1 Phase A model weakness: 5/10 seeds miss ≥3/5 Gate 1/2 aggregate | Medium | Session-long | Henri | Open (accepted debit) | Documented + spec-recalibrated in v1.11. Phase 2 scale-out work addresses via §7.3 |
| I-03 | D7 Phase 2 MVP model quality: dealer_inventory fails G1+G2 on minimal market | Medium | 2026-04-18 | Henri | Open (accepted debit) | Gate 3 passes strict. Scale-out or richer market fixes |
| I-04 | HDP-HMM deferred (D3) — fixed K=4 regime classifier | Low | Phase 1 | Henri | Monitoring | Upgrade path via v0.3; no load-bearing impact |
| I-05 | Phase 3 not yet scoped in spec | Medium | 2026-04-18 | Henri | Open | Needs spec v2.x revision post-Phase 2 scale-out |
| I-06 | Real Speckle-and-Spot data wiring not planned in detail | Medium | 2026-04-18 | Henri | Open | External dependency; see R-02 |
| I-07 | D7 expanded to cover hedging_demand (Gates 1+2 still fail on minimal synthetic market) | Medium | 2026-04-18 | Henri | Open (accepted debit) | Mirror of oil D1. Scale-out or richer market fixes |
| I-08 | D8 same-target aggregation normalization (dealer_inventory + hedging_demand both target VIX_30D_FORWARD) | Medium | 2026-04-18 | Henri | Open | Blocks Shapley attribution claims. Fix: contribution-space aggregation in attribution harness |
| I-09 | D9 Gate 3 is DeskProtocol conformance only (runtime hot-swap needs real Controller.decide harness) | High | 2026-04-18 | Henri | Closed 2026-04-18 | Closed at tag `gate3-runtime-harness-v1.14`. `eval/hot_swap.py::build_hot_swap_callables` shipped; 7 integration callsites migrated; Controller retire-exclusion fix (B-4) landed alongside at `controller/decision.py:96-104`. Full suite 397 passed + 1 skipped. Scope caveat: pre-v1.14 Gate 3 passes are attribute-conformance only; v1.14 onward is runtime hot-swap. See capability_debits.md D9 + D-14 decision row below. |

## Decisions (log of key choices + rationale)

| ID | Date | Decision | Rationale | Forks considered | Reversibility |
|---|---|---|---|---|---|
| D-01 | 2026-04-17 | Ship Phase 1 with 6 capability debits, all in-budget | Debits are named + mitigated + proportional to scope | Strict reading: demand 5/5 Gate pass on every seed → blocks Phase 1 | Reversible: fail Phase 1 if auditor rejects debits |
| D-02 | 2026-04-17 | Reliability gate 28d → 7d (v1.6) | Synthetic-only; instrumentation compensates | Keep at 28d; drop entirely | Reversible via spec edit |
| D-03 | 2026-04-17 | Reliability gate 7d → 48h (v1.8) | Still partially gut-feel; daily-cycle-bug argument | Keep at 7d | Reversible |
| D-04 | 2026-04-17 | Reliability gate 48h → 4h (v1.10) | Daily-cycle-bug argument didn't apply to DuckDB research prototype | Keep at 48h | Reversible |
| D-05 | 2026-04-17 | Feed-reliability: full Page-Hinkley (not stub) | User answered via AskUserQuestion | Stub-only; skip Layer 3 | Reversible |
| D-06 | 2026-04-17 | Feed-reliability: all-regimes retirement | §7.2 harmful-case parity | Current-regime-only | Reversible |
| D-07 | 2026-04-18 | Shapley-first reinstatement via `historical_shapley_share` + direct-insert fallback | Original plan's `propose_and_promote_from_shapley` would re-weight all desks (invasive) | Ship direct-insert only (simpler) | Reversible |
| D-08 | 2026-04-18 | Phase 2: MVP scope (1 desk) before full 5-desk | User answered via AskUserQuestion | All 5 at once; external checkpoint first | Reversible — scale-out is planned next |
| D-09 | 2026-04-18 | Phase 2: sibling `sim_equity_vrp/` (not rename `sim/` → `sim_oil/`) | Smaller diff; oil runs alongside | Rename | Reversible but touches many imports |
| D-10 | 2026-04-18 | §12.2 item 2 Logic gate recalibrated: separate strict invariants from capability claim | Reality-calibrated (5/10 seeds hit full aggregate) | Demand 10/10; block Phase 1 | Hard to reverse — tests encoded |
| D-11 | 2026-04-18 | Desk 2 pre-implementation design review request-changes integrated (5 blocking + 6 major) before any code landed | Critic-first: addresses B-1 (test indexing), B-2 (RNG isolation + golden fixtures), B-3 (Gate 3 recalibration + D9), B-4 (drop Shapley criterion + D8), B-5 (data_sources routing), + M-1/M-2/M-3/M-6 | Accept original plan as-is (fake Gate 3, silent dealer_inventory drift risk, unbacked Shapley claim, decorative feed_names, train/serve mismatch) | Reversible — re-plan if pattern doesn't scale to Desk 3+ |
| D-12 | 2026-04-18 | Golden-fixture regression test for dealer_inventory pinned as load-bearing gate | Catches silent drift if hedging_demand (or future) extension perturbs the RNG stream | Rely on determinism-by-inspection | Re-recording hashes requires spec v1.x dependency-version revision |
| D-13 | 2026-04-18 | G1/G2 metrics pinned as exact regression values instead of soft-assert | Regression signal kicks in on silent model drift | Print-only per MVP precedent | Re-pinning is a deliberate commit when a model change justifies it |
| D-14 | 2026-04-18 | Fix-baseline-before-scale-out: close D9 Gate 3 runtime harness at v1.14 (before Desk 3), not after. Closed-loop exercise surfaced B-4 Controller retire-exclusion bug that scale-out would have multiplied. | Shipping 3 more desks on top of a tautological Gate 3 would have hidden the B-4 bug in 3× more callsites; closing D9 first lets scale-out inherit a working harness. Pre-implementation design review (5 blocking + 6 major findings) widened original scope from "fix 2 equity-VRP tests" to "fix 7 integration callsites + ship Controller fix" — the right scoping came from critic-first review, not from the original plan. | Ship a targeted Desk 2 patch (fix the 2 equity-VRP lambdas only) then close D9 as scope caveat; B-4 bug would have surfaced later under Phase A/B/C stress | Hard to reverse — test migration + Controller fix are load-bearing |

---

## Maintenance

Update on every phase milestone. Every decision with non-obvious rationale gets a D-entry. Every debit opened goes into `capability_debits.md` and gets cross-referenced here as an I-entry. Every risk with a status change gets a new row (not an in-place edit — preserve audit trail).
