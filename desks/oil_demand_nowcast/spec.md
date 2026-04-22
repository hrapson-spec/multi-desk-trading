# `oil_demand_nowcast` Desk — Spec

v1.16 merged successor to the legacy `demand` desk plus the alpha portion of
the legacy `macro` desk. Macro residual is demoted to regime-conditioning state
via `regime_classifier`.

## Purpose

Mixed-frequency oil-demand nowcast. Forecasts global activity / refinery demand
/ product demand and maps them to a signed 1-week oil return contribution. Low
confidence outside fresh-release windows.

Absorbs:

- current `demand` desk scope in full.
- current `macro` desk's demand-transmission alpha content.

Does NOT own:

- scheduled supply / event-driven disruption — `supply_disruption_news`.
- cross-asset macro beta — `regime_classifier` (conditioning only).
- inventory-level dynamics — `storage_curve`.

## Emission

- Controller-facing `target_variable`: `wti_front_1w_log_return` (shared oil family unit).
- `point_estimate`: signed 1-week log-return contribution from the nowcast.
- Low confidence when only stale slow-moving data is available.

## Internal auxiliary labels (never emitted to Controller)

- `physical_demand_surprise_z`
- `refinery_run_surprise_z`

## Primary feeds

- `eia_wpsr`
- additional mixed-frequency release feeds (IEA OMR, JODI, PMIs) wire via
  `config/data_sources.yaml` as they are added.

## Phase 2 scope

Ridge-level classical head (`ClassicalOilDemandNowcastModel`, inherits from the
legacy `ClassicalDemandModel` until C12 cleanup inlines the implementation).
Full mixed-frequency state-space / dynamic-factor nowcast is a §7.3 escalation
under debit D1.
