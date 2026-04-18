# Dealer-inventory desk — spec

**Phase 2 MVP (spec v1.12 §14.7).** Load-bearing equity-VRP desk. Analogue to the oil `storage_curve` desk's portability role: proves the architecture runs end-to-end on a non-oil asset class with zero shared-infrastructure changes.

## Purpose

Forecast next-period 30-day forward implied vol (target `VIX_30D_FORWARD`) from dealer positioning signals. Economic intuition: when dealers get short vol, they hedge by buying vol products, pushing realised and implied vol higher in the following days.

## Inputs

- `dealer_flow`: dealer net positioning in vol products (AR(1) process in the synthetic market).
- `vega_exposure`: dealer_flow × current vol level (a sensitivity-weighted positioning).
- `market_price`: the vol-level series (VIX proxy), used for ridge fitting and directional-score computation.

In production (not Phase 2 MVP scope): dealer flow data would come from options market-maker positioning reports (CFTC COT-equivalent for equity options, CBOE/OCC positioning stats) or proprietary Speckle-and-Spot feeds.

## Output

`Forecast(target_variable="vix_30d_forward", point_estimate=<predicted vol>, directional_claim.sign="positive", staleness=<from feed_incidents>)`.

## Model

`ClassicalDealerInventoryModel` — ridge over 5 features:
- `dealer_flow[i-1]`, `dealer_flow.mean(window)`, `dealer_flow_trend(window)`
- `vega_exposure[i-1]`, `vega_exposure.mean(window)`

Fit target: log-return of vol over `horizon_days=3`. Prediction: next-period vol level.

Phase 2 MVP capability-claim debit (parallel to oil D1): ridge-on-5-features is a deliberately modest model. The architectural test is whether this desk passes the three hard gates and composes with LODO/Shapley. Model quality escalation (§7.3) is a Phase 2 scale-out item.

## Gates

- **Gate 3 (runtime hot-swap)**: strict — Controller.decide() must run to completion with either `DealerInventoryDesk` or a `StubDesk`-swap. Portability invariant. Evidenced by `tests/test_dealer_inventory_gates.py::test_dealer_inventory_classical_passes_three_gates_on_mvp_market` via `eval.hot_swap.build_hot_swap_callables`. Attribute-conformance as `StubDesk` → `DeskProtocol` remains a necessary precondition (`test_dealer_inventory_gate3_always_passes_strict`). D9 closed 2026-04-18 at tag `gate3-runtime-harness-v1.14`.
- **Gate 1 (skill)**: capability claim — ridge must beat the vol-random-walk baseline on the held-out split.
- **Gate 2 (sign preservation)**: capability claim — positive-sign convention dev → test.

## Phase 2 scale-out

Four additional desks follow the dealer_inventory template:
- `hedging_demand` (↔ supply)
- `term_structure` (↔ demand)
- `earnings_calendar` (↔ geopolitics)
- `macro_regime` (↔ macro)

All share the same interface and shared-infrastructure; none requires changes to `bus/`, `controller/`, `persistence/`, `research_loop/`, `attribution/`, `grading/`, `provenance/`, `eval/`, `soak/`, or `scheduler/`.
