# Project management artefacts

Three living documents that track the multi-desk-trading project beyond the architectural spec.

| File | Purpose | Update cadence |
|---|---|---|
| [`master_plan.md`](master_plan.md) | Milestones + dates + deliverables register. Phase 1 / Phase 2 MVP / Phase 2 scale-out / Phase 3 timeline. | On every milestone ship |
| [`raid_log.md`](raid_log.md) | Strategic Risks, Assumptions, Issues, Decisions. Forward-looking. | On every risk/assumption/decision change |
| [`problem_log.md`](problem_log.md) | Defects / bugs / regressions and their resolution. Backward-looking audit trail. | On every P-entry |

Adjacent artefacts (not under `pm/` but referenced here):
- `../architecture_spec_v1.md` — authoritative spec.
- `../phase1_completion.md`, `../phase2_mvp_completion.md` — phase-exit evidence manifests.
- `../capability_debits.md` — consolidated debit log (per §12.2 item 6).

One-off execution briefs in this folder (per v1.16 desk-roster restructure, adopted external review in `docs/first_principles_redesign.md`):
- [`supply_disruption_news_engineering_commission.md`](supply_disruption_news_engineering_commission.md) — merged-oil desk absorbing current `supply` + `geopolitics` + untracked `planned_supply_balance/` + `disruption_risk/` WIP artefacts.
- [`oil_demand_nowcast_engineering_commission.md`](oil_demand_nowcast_engineering_commission.md) — merged-oil desk absorbing current `demand` + macro alpha.
- [`surface_positioning_feedback_engineering_commission.md`](surface_positioning_feedback_engineering_commission.md) — merged equity-VRP desk absorbing `dealer_inventory` + `hedging_demand` under the no-signed-flow constraint.

This folder was created 2026-04-18 at Phase 2 MVP ship. Before that, project state lived in the spec + git tags. PM artefacts formalise the tracking now that two phases have exited.
