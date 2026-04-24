# S4-0 recorded replay dry-run plan

- **Status**: planning baseline, tag `v2-s4-0-plan-0.1`
- **Created**: 2026-04-24
- **Owner**: Henri Rapson
- **Stage**: S4-0 recorded replay
- **Predecessor**: `v2-phase-b-complete-0.1`

## 1. Objective

S4-0 is a no-capital operational rehearsal using recorded replay data for the
WTI / oil family. The objective is to prove that a declared market session can
be processed end to end with reviewer-grade evidence from raw input through
normalization, feature generation, forecast, decision, simulated execution,
ledger, incident handling, replay, restore, and stop/go assessment.

S4-0 does not make a profitability, production-readiness, live-trading, or
real-capital claim.

## 2. Locked Decisions

| Decision area | S4-0 decision |
|---|---|
| Target family | WTI / oil family |
| Initial instruments | NYMEX WTI crude oil futures; CL front-month and next-month contracts |
| Explicit test area | Contract-roll handling |
| Data mode | Recorded replay first |
| First run duration | One full declared trading session |
| Expansion condition | Move to one trading week only after a clean one-session rehearsal |
| Data-source path | External researcher recommends sources before selection |
| Evidence standard | Strict reviewer-grade evidence pack |

## 3. Scope

In scope:

- Recorded replay source selection and entitlement evidence.
- CL front-month and next-month symbol mapping.
- Contract-roll reference data and roll-handling test records.
- Raw feed capture from replay input.
- Normalized feed output.
- Data-gap, duplicate, stale-feature, and timestamp reports.
- Feature generation and forecast receipt capture.
- Decision and abstention receipt capture.
- Simulated order, fill, and execution ledger records.
- Kill-switch, manual override, incident, replay, restore, and monitoring evidence.
- Final stop/go assessment.

Out of scope:

- Brent, refined products, ETFs, broad macro instruments, or multi-family expansion.
- Delayed live feed or true live feed operation.
- Broker or exchange order routing.
- Real-money execution.
- Profitability validation.
- Public or investor-facing performance claims.

## 4. Hard Gates Before Run

S4-0 cannot start until all hard gates are satisfied:

| Gate | Required evidence |
|---|---|
| Data licence clarity | Written summary covering non-display use, local storage, replay, retention, and reviewer access. |
| Entitlement proof | Vendor or account evidence showing the dataset is available for the declared symbols and dates. |
| Timestamp semantics | Documented exchange/vendor timestamp fields and timezone handling. |
| Contract mapping | Declared front-month and next-month symbols plus roll rule for the chosen window. |
| Run declaration | Fixed run ID, session date, session window, instruments, code commit, and evidence root. |
| Stop criteria | Green/amber/red criteria accepted before the run starts. |

## 5. Run Design

S4-0 has three execution steps:

| Step | Purpose | Exit condition |
|---|---|---|
| S4-0A readiness | Select data source, licence path, symbols, session, and evidence root. | All hard gates satisfied. |
| S4-0B one-session rehearsal | Run one declared recorded replay session end to end. | Report completed with stop/go assessment. |
| S4-0C one-week expansion | Repeat across one trading week. | Allowed only after S4-0B has no unresolved blocker issue. |

## 6. Pre-Registered Stop/Go Criteria

Green:

- All required evidence classes exist and are hashable.
- Raw and normalized feed logs are captured for the full declared session.
- Data gaps, duplicates, and stale features are reported even if counts are zero.
- Forecast, decision, abstention, simulated order, simulated fill, and ledger
  records reconcile for sampled events.
- Incident log exists and contains every manual drill or exception.
- Replay reproduces the run or produces a documented, bounded divergence.
- Restore drill completes and writes a restore report.
- No open P0/P1 incident remains at assessment time.

Amber:

- The run completes but has non-blocking exceptions.
- Evidence is complete, but at least one reconciliation or replay divergence
  requires owner review.
- A P2 incident remains open with a mitigation owner and explicit due date.

Red:

- Data licence or entitlement position is unclear.
- Required evidence classes are missing.
- Raw-to-normalized or decision-to-ledger reconciliation cannot be traced.
- Replay fails without a bounded explanation.
- Restore fails.
- A P0/P1 incident remains unresolved.
- The run accidentally connects to a broker or real-money pathway.

## 7. Clean Run Definition

A one-session rehearsal is clean only if:

- Raw and normalized feed logs are captured.
- Forecast receipts are generated.
- Decision and abstention receipts are generated.
- Simulated execution ledger reconciles.
- Incident log exists even if no incidents occur.
- Replay can reproduce the run or explain divergences.
- Restore path is documented and exercised.
- Stop/go assessment is completed.

## 8. Required Outputs

- S4-0 evidence manifest.
- S4-0 run declaration.
- S4-0 incident register.
- S4-0 replay verification report.
- S4-0 restore report.
- S4-0 reconciliation summary.
- S4-0 post-run report.

## 9. Next Blocking Decision

The next blocking decision is data-source selection. No S4-0 execution work
should claim readiness until the external research brief has resolved vendor
fit, timestamp semantics, entitlement evidence, licence boundaries, and local
replay/storage rights for the selected source.
