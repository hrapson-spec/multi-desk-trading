# `surface_positioning_feedback` Desk — Engineering Commission

**Project**: multi-desk-trading
**Date issued**: 2026-04-22
**Status**: commissioned (stub), not yet implemented
**Audience**: engineer owning the equity-VRP rename + merge
**Authorising context**:
- `docs/first_principles_redesign.md` (adopted pasted review)
- `~/.claude/plans/the-architecture-is-already-unified-adleman.md` (C8 + C9 + C11)

---

## 1. Objective

Rename `desks/dealer_inventory/` → `desks/surface_positioning_feedback/` and merge `desks/hedging_demand/` into it. Under the current observation layer, `sim_equity_vrp/` has no signed option flow, so the pasted review's merge rule applies: without signed flow, `customer_flow_pressure` cannot exist as a separately-identifiable standalone desk.

---

## 2. Problem statement

Per the pasted review and the D7 debit:

- What is observable is market-wide surface positioning, not true dealer books.
- `dealer_inventory` and `hedging_demand` are scored on the same `VIX_30D_FORWARD` level target, which is not the right quantity for either mechanism.
- `hedging_demand`'s real target is skew-delta, which does not aggregate cleanly under `controller/decision.py` raw-sum.
- Current Gate 2 sign preservation fails on both desks (D7 open).

The redesign retargets the unified merged desk to a signed 3-day vol-delta, with realized-vol surprise as an internal auxiliary label.

---

## 3. Target redesign

### 3.1 Controller-facing emission

- `target_variable = "vix_30d_forward_3d_delta"` (`contracts.target_variables.VIX_30D_FORWARD_3D_DELTA` — added at C2 of the plan).
- `point_estimate`: signed 3-day VIX-30d-forward delta contribution.

### 3.2 Internal auxiliary label

- `next_session_rv_surprise = realised_next_session_rv − fair_vol_baseline[t]`
  - `fair_vol_baseline` is a decision-time-safe trailing-k-day mean of `vol_level` with an explicit k-day lag, added to `EquityObservationChannels` in C11.
  - Not available before C11 ships; the desk should degrade gracefully if the channel is absent.

### 3.3 Absorbs

- Current `dealer_inventory` scope in full (`dealer_flow`, `vega_exposure`).
- Current `hedging_demand` scope in full (`hedging_demand_level`, `put_skew_proxy`).

### 3.4 Does NOT own

- Earnings-event vol expansion — `earnings_calendar` (planned Phase 2 scale-out, explicitly kept separate per pasted review).
- Regime conditioning — `regime_classifier`.
- True dealer-specific dealer-book signals — unavailable under current public-data constraint; reserved for a future `dealer_inventory_pressure` split if richer observables arrive.

---

## 4. Deliverables

### 4.1 Desk implementation (C8)

- Rename `desks/dealer_inventory/` → `desks/surface_positioning_feedback/`.
- Delete `desks/hedging_demand/`.
- New desk reads all four channels (`dealer_flow`, `vega_exposure`, `hedging_demand_level`, `put_skew_proxy`) from the merged `channels.by_desk["surface_positioning_feedback"]` key.
- Emits `VIX_30D_FORWARD_3D_DELTA` via the fitted delta head. Directional score uses the fitted delta mean (not a hand-built heuristic).

### 4.2 Sim-side merge (C9)

- `sim_equity_vrp/observations.py` — collapse `by_desk["dealer_inventory"]` and `by_desk["hedging_demand"]` into a single `by_desk["surface_positioning_feedback"]` observation with four component arrays.
- **Do not modify** `sim_equity_vrp/latent_state.py`. The seed-offset convention (main, +1, +2, +3) at `latent_state.py:21-27` is load-bearing for D12 golden fixtures.

### 4.3 fair_vol_baseline channel (C11)

- Add `fair_vol_baseline: np.ndarray` to `EquityObservationChannels`.
- Reference implementation: `fair_vol_baseline[t] = vol_level[t-k-1 : t-1].mean()` with explicit k-day lag (k config-pinned). Decision-time safe.
- Unit test: `fair_vol_baseline[t]` is a strict function of `vol_level[<t]`.

### 4.4 Tests

- Rename `tests/test_dealer_inventory_gates.py` → `tests/test_surface_positioning_feedback_gates.py`.
- Delete `tests/test_hedging_demand_gates.py`.
- Update `tests/test_attribution_shapley.py`, `tests/test_attribution_lodo.py`, `tests/test_phase2_equity_vrp_portability.py`, `tests/test_phase2_portability_contract.py`.
- Re-record D12 golden-fixture pins (justified under D12's "v1.x dependency-version revision" clause; v1.16 qualifies).
- Re-record D13 G1/G2 regression metric pins.

---

## 5. Minimum acceptance criteria

- Gate 3 runtime hot-swap passes on the merged desk.
- `compute_shapley_grading_space` produces non-degenerate values; same-target normalization test `test_grading_space_same_target_scale_neutrality` still passes.
- Directional score is the fitted delta head, not a heuristic.
- Portability test has zero diff in `bus/`, `controller/`, `persistence/`, `eval/hot_swap.py`, `provenance/`, `scheduler/`.

---

## 6. Non-goals

- Adding signed option flow to `sim_equity_vrp/` (Phase 3).
- Splitting the desk back into `dealer_inventory_pressure` + `customer_flow_pressure` (contingent on Phase 3 sim upgrade).
- Implementing a full regime-conditional forward-vol forecaster (C11 ships the minimum trailing-mean-with-lag).

---

## 7. Questions the engineer must answer

1. What exact k-day lag and window size does `fair_vol_baseline` use? Is it tested against a leakage probe?
2. How does the merged desk's directional score relate to the fitted delta head?
3. Does `compute_shapley_grading_space` still preserve same-target scale neutrality when one desk replaces two prior desks that shared the target?
4. What is the D12 re-record provenance chain across C8, C9, and C11?

---

## 8. Success condition

A single merged equity-VRP desk whose emission is a signed 3-day vol-delta contribution (unit-compatible with the frozen Controller raw-sum), whose internal auxiliary surprise label uses only decision-time-safe observables, and whose Gate 2 sign preservation is no longer confounded by mechanism-unit mismatch.
