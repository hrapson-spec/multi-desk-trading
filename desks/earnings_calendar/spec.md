# `earnings_calendar` Desk — Spec

v1.16 X1. Event-driven equity-VRP desk for vol-expansion around
scheduled earnings clusters. Explicitly kept separate from
`surface_positioning_feedback` per the adopted pasted review in
`docs/first_principles_redesign.md` ("otherwise it will contaminate
hedging_demand [now surface_positioning_feedback]"). W10 shipped the
structural skeleton; **X1 landed the real earnings-event channel and
closed D-17** — the desk now has measured Gate 1 skill against the
zero-return baseline (14.66% relative improvement on the pinned probe).

## Purpose

Forecast signed VIX-30d-forward 3-day delta contribution around
scheduled earnings releases. Near-zero emission outside activation
windows (sparse-event framing mirroring `supply_disruption_news`).

Does NOT own:
- Dealer / surface-positioning feedback — `surface_positioning_feedback`.
- Regime conditioning — `regime_classifier`.
- Single-name (ticker-level) event impact — scope is index-level
  (SPX / VIX); single-name vol is out of scope.

## Emission

- Controller-facing `target_variable`: `vix_30d_forward_3d_delta`
  (shared equity family unit). Unit-consistent with
  `surface_positioning_feedback` under `controller/decision.py:94-112`
  raw-sum aggregation.
- `point_estimate`: signed 3-day vol-delta prediction.
- `directional_claim.sign`: derived from the fitted head (matches
  `point_estimate` sign).

## Primary feeds

- `earnings_calendar_feed` (synthetic until real feed arrives;
  placeholder in `config/data_sources.yaml`).
- `vix_eod` (shared with `surface_positioning_feedback`).

## X1 scope (current)

`ClassicalEarningsCalendarModel`: 5-feature ridge on
- `earnings_cluster_size[t]` — primary mechanism feature; count of
  events in the trailing 5-day window.
- `earnings_event_indicator[t]` — binary today-is-event flag.
- `event_density` — trailing-10d mean of the indicator.
- `current_vol` — `market_price[t-1]`.
- `vol_zscore` — `(current_vol - trailing_mean) / trailing_std`.

Emission target `VIX_30D_FORWARD_3D_DELTA` (signed 3-day vol delta).
Point estimate is the fitted delta directly; directional score equals
the point estimate (fitted-head driven, not a heuristic).

### Mechanism

The sim at `sim_equity_vrp/latent_state.py` generates earnings events
with a forward correlation to `vol_shocks_unscaled` at a 2-step lead
(default `earnings_vol_corr=0.45`, `earnings_vol_lead=2`). Because
`vol_shocks_unscaled[k]` drives `vol_level[k+1]`, the observable
`earnings_cluster_size[t]` has a real, learnable predictive
relationship with `vol_level[t+3]` — matching the desk's 3-day
horizon. The Pearson r on a 1500-day path seed=42 is 0.15 (test:
`test_earnings_channel_correlates_with_future_vol`).

### Architectural invariants

- DeskProtocol conformance.
- Gate 3 hot-swap via `eval.hot_swap.build_hot_swap_callables`.
- Same-target composition with `surface_positioning_feedback` under
  the Controller's raw-sum aggregation (§8.2).
- D12 golden fixtures on dealer_flow / vega_exposure / vol_level /
  spot_log_price / hedging_demand preserved byte-identically (new
  channel generated at seed+4 AFTER all pre-X1 draws).
- Gate 1 skill against `zero_return_baseline` restored (14.66%
  relative improvement on seed 7; D-17 closed).

## Follow-on scope (Phase 3)

Real-data wiring:
- OCC open-interest feed for vol-surface richness.
- Company release calendars (synthetic placeholder until Phase 3).
- Structured event-class schema (earnings surprise / guidance revision
  / M&A) replacing the single binary indicator.
- State-conditioning on macro regime + vol-surface shape.

Kept in commission §5 for reference.
