# `earnings_calendar` Desk — Engineering Commission

**Project**: multi-desk-trading
**Date issued**: 2026-04-22
**Status**: commissioned; W10 ships a structurally-complete skeleton; full alpha rebuild is a follow-on wave.
**Authorising context**:
- `docs/first_principles_redesign.md` (adopted pasted review — pasted review explicitly keeps `earnings_calendar` as a separate equity event desk).
- `docs/pm/master_plan.md` 2026-05-23 target.

---

## 1. Objective

Event-driven equity-VRP desk that forecasts vol-delta around scheduled earnings releases. Explicitly kept separate from `surface_positioning_feedback` per the adopted pasted review ("otherwise it will contaminate hedging_demand [now surface_positioning_feedback]").

The desk must remain compatible with the frozen architecture:
- no shared-infra changes;
- preserve §8.4 portability claim;
- preserve Gate 3 hot-swap semantics;
- controller-facing emission stays in decision-space units.

---

## 2. Mechanism

Upcoming earnings releases → cluster-dependent implied-vol expansion → cross-sectional skew + ATM vol moves → signed 3-day VIX-30d-forward delta contribution.

Observable: earnings calendar (per-ticker scheduled release dates), proximity/clustering metrics, current vol-surface state, event calendar conflicts with macro releases.

---

## 3. Emission

- `target_variable = "vix_30d_forward_3d_delta"` (shared equity family unit).
- Near-zero outside activation windows (active-window-only desk — mirrors `supply_disruption_news` sparse-event framing).
- Internal auxiliary label: `expected_cluster_vol_expansion` (not emitted).

---

## 4. W10 skeleton scope (shipped 2026-04-22)

Structurally-complete desk that satisfies:
- DeskProtocol conformance.
- Gate 3 runtime hot-swap.
- `controller/decision.py:94-112` raw-sum aggregation with `surface_positioning_feedback` (both emit `VIX_30D_FORWARD_3D_DELTA`).
- `config/data_sources.yaml` subscription.
- Minimum 1 Phase 2 scale-out test.

Classical: minimal ridge on vol-surface proxies only (no real earnings calendar channel in the sim yet). Gate 1/2 performance is expected weak — logged as open debit D-17 (to be opened at ship time) pending the earnings-channel sim build.

---

## 5. Full build scope (follow-on wave)

- Add earnings-event channel to `sim_equity_vrp/` (per-ticker scheduled release dates, mock clustering).
- Structured event-classification mirror of `supply_disruption_news`:
  - event class (regular earnings, guidance revision, M&A surprise)
  - cluster size
  - sector weight
  - ATM-vol pressure prior
- Calibrated probabilistic impact model on top of the schema.
- State-conditioning on current surface state and macro-regime.
- Real data wiring (post-Phase 3): Bloomberg-style earnings calendar + scraped IR announcements.

---

## 6. Data-source feeds

- `earnings_calendar_feed` (synthetic until real feed arrives).
- `vix_eod` (shared with `surface_positioning_feedback`).
- `cboe_open_interest` (shared).
- `option_volume` (shared).

---

## 7. Success condition

Desk emits a signed 3-day vol delta that composes cleanly under the Controller's raw-sum aggregation alongside `surface_positioning_feedback`, passes Gate 3 runtime hot-swap, and honours the same-target D8 normalization in `attribution.compute_shapley_grading_space`. Model-quality (Gate 1/2) is a Phase 2 scale-out escalation item; W10 ships the architectural scaffolding only.
