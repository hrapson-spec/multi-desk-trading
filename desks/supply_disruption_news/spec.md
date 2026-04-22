# `supply_disruption_news` Desk — Spec

v1.16 merged successor to the legacy `supply` + `geopolitics` desks, plus the
untracked `planned_supply_balance` and `disruption_risk` WIP artefacts from the
superseded first_principles_redesign direction.

## Purpose

Event-hurdle forecaster: activation probability × conditional effect size.
Emits near-zero outside activated states. Absorbs:

- realised flow-supply disruptions
- future supply news / policy announcements (OPEC quota surprises, SPR etc.)
- precautionary / geopolitical risk shocks
- logistics / storage / conversion bottlenecks
- event-led demand shocks

Does NOT own:

- inventory-level dynamics — `storage_curve`.
- broad physical demand — `oil_demand_nowcast`.
- cross-asset / macro beta — `regime_classifier` (conditioning only).

## Emission

- Controller-facing `target_variable`: `wti_front_1w_log_return` (shared oil family unit).
- `point_estimate`: signed 1-week log-return contribution from the hurdle model.
- Default behaviour outside activation: `point_estimate = 0.0` with neutral confidence.

## Internal auxiliary labels (never emitted to Controller)

- `p_disruption`
- `signed_barrel_impact`
- `planned_supply_surprise_z`

## Primary feeds (via `config/data_sources.yaml`)

- `opec_announcement`
- `eia_wpsr`

## Phase 2 scope

Ridge-level classical head (`ClassicalSupplyDisruptionNewsModel`, inherits from
the legacy `ClassicalGeopoliticsModel` until C4b inlines the implementation).
Full hurdle / event-study rebuild is a §7.3 escalation under debit D1.
