# `earnings_calendar` Desk — Spec

v1.16 W10 skeleton. Event-driven equity-VRP desk for vol-expansion
around scheduled earnings clusters. Explicitly kept separate from
`surface_positioning_feedback` per the adopted pasted review in
`docs/first_principles_redesign.md` ("otherwise it will contaminate
hedging_demand [now surface_positioning_feedback]").

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

## W10 skeleton scope

`ClassicalEarningsCalendarModel`: 3-feature ridge on vol-level / vol-of-vol
proxies drawn from `channels.market_price`. No real earnings-proximity
features yet — the sim has no earnings channel. Gate 1/2 performance is
expected weak until the earnings channel lands; this is a Phase 2
scale-out follow-on under the commission at
`docs/pm/earnings_calendar_engineering_commission.md`.

Architectural invariants the W10 skeleton satisfies:
- DeskProtocol conformance.
- Gate 3 hot-swap via `eval.hot_swap.build_hot_swap_callables`.
- Same-target composition with `surface_positioning_feedback` under
  the Controller's raw-sum aggregation.

## Phase 2 follow-on scope

See commission §5 for the full event-schema rebuild. Minimum additions
needed to reach Gate 1/2 skill:
- Earnings-event channel in `sim_equity_vrp/` (scheduled release dates,
  cluster size, sector weight).
- Structured event-schema model (class + state conditioning).
- Calibrated impact distribution.
