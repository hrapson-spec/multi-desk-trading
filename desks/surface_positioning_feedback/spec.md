# `surface_positioning_feedback` Desk — Spec

v1.16 merged successor to the legacy `dealer_inventory` + `hedging_demand`
equity-VRP desks. Merge rule applies because `sim_equity_vrp/` has no signed
option flow — the pasted review's "if no signed flow, do not keep
`customer_flow_pressure` standalone" constraint is satisfied by merging both
proxies into one surface-positioning desk.

## Purpose

Forecast next-session vol-surface feedback: aggregate option positioning
(gamma/vanna/charm proxies) × spot move → dealer hedging feedback →
realised-vol regime.

Absorbs:
- current `dealer_inventory` scope in full (dealer_flow + vega_exposure
  proxies).
- current `hedging_demand` scope in full (hedging_demand_level + put_skew_proxy).

Does NOT own:
- Earnings-event vol expansion — `earnings_calendar` (planned Phase 2
  scale-out, explicitly kept separate per pasted review).
- Regime conditioning — `regime_classifier`.
- True dealer-book-specific signals — unavailable under current
  public-data constraint; reserved for a future `dealer_inventory_pressure`
  split if richer observables arrive (Phase 3 prerequisite).

## Emission

- Controller-facing `target_variable`: `vix_30d_forward_3d_delta` (shared
  equity family unit, added to `contracts/target_variables.py` at v1.16 C2).
- `point_estimate`: signed 3-day vol-delta prediction. NOT a vol level —
  this is the unit rebase that makes the equity family raw-summable under
  `controller/decision.py:94-112`.
- `directional_claim.sign`: derived from the fitted delta head (matches
  `point_estimate`'s sign). Replaces the legacy `dealer_inventory`
  heuristic `flow_last + 0.25 * vega_normalized`.

## Internal auxiliary label (planned, C11)

- `next_session_rv_surprise` = realised_next_session_rv − fair_vol_baseline[t]
  - Depends on a decision-time-safe `fair_vol_baseline` channel added to
    `EquityObservationChannels` at C11 (trailing k-day mean of vol_level
    with explicit k-day lag).
- Not emitted to Controller — internal training signal only.

## Primary feeds (via `config/data_sources.yaml`)

- `vix_eod`
- `cboe_open_interest`
- `option_volume`

## Phase 2 scope

Composite ridge: `ClassicalSurfacePositioningFeedbackModel` wraps both
legacy classical models (`ClassicalDealerInventoryModel` +
`ClassicalHedgingDemandModel`), fits each on its own channel set, and
averages the fitted delta predictions at serve time. Full monotone-GAM /
GBDT rebuild is a §7.3 escalation under debit D7.

## Channel-read transition plan

- **C8 (this commit)**: desk reads both legacy channel keys
  (`by_desk["dealer_inventory"]` + `by_desk["hedging_demand"]`) via the
  `_read_channels` helper. Prefers a merged key if present; falls back to
  the two legacy keys otherwise.
- **C9**: `sim_equity_vrp/observations.py` merges both keys into a single
  `by_desk["surface_positioning_feedback"]` with the four component names
  preserved. The `_read_channels` helper's preference for the merged key
  picks this up automatically without a desk-code change.
