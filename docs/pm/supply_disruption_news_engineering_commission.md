# `supply_disruption_news` Desk — Engineering Commission

**Project**: multi-desk-trading
**Date issued**: 2026-04-22
**Status**: commissioned, not yet implemented
**Audience**: engineer owning the oil supply-news desk rebuild
**Authorising context**:
- `docs/first_principles_redesign.md` (adopted pasted review)
- `docs/architecture_spec_v1.md` v1.16
- `~/.claude/plans/the-architecture-is-already-unified-adleman.md` (C4)

**Supersedes**: the earlier `disruption_risk_engineering_commission.md` (scope was narrower — just the `geopolitics` successor). This commission absorbs that scope plus fast-supply news into one merged desk.

---

## 1. Objective

Build the new oil `supply_disruption_news` desk that replaces four legacy directories (`desks/supply/`, `desks/geopolitics/`, `desks/planned_supply_balance/`, `desks/disruption_risk/` — the last two are untracked WIP artefacts from the superseded first_principles_redesign direction).

The desk is an **event-hurdle model**: activation probability × conditional effect size. It emits near-zero outside activated states.

The desk must remain compatible with the frozen architecture:
- no shared-infra changes,
- preserve the §8.4 portability claim,
- preserve Gate 3 hot-swap semantics,
- Controller-facing emission stays in decision-space units.

---

## 2. Problem statement

The pasted review's diagnosis of the legacy `supply` and `geopolitics` desks:

- `supply` currently conflates fast information repricing (OPEC/outage/sanctions/shipping news) with slow physical adjustment (balance, inventories).
- `geopolitics` is not a separable continuous factor — it is a source of supply-news or precautionary-demand events.
- Both desks are scored like dense continuous forecasters even though the real mechanism is sparse and event-driven.
- Ridge-on-summary-features does not recover event-conditional effects.

The redesign reframes the problem as a hurdle model: most days emit near-zero; activation days carry the signal.

---

## 3. Target redesign

### 3.1 Controller-facing emission

- `target_variable = "wti_front_1w_log_return"` (`contracts.target_variables.WTI_FRONT_1W_LOG_RETURN`)
- `point_estimate`: signed 1-week log-return contribution from the hurdle model.
- Near-zero outside activation windows (default behaviour: `point_estimate = 0.0` with neutral confidence).

### 3.2 Internal auxiliary labels (never emitted to Controller)

- `p_disruption`: activation probability.
- `signed_barrel_impact`: conditional barrel-weighted impact sign and magnitude.
- `planned_supply_surprise_z`: standardised surprise vs expectation for scheduled supply releases (OPEC quota changes, JODI, EIA WPSR production component).
- Optional internal target for falsification: Δ(prompt calendar spread) over 1–5d.

### 3.3 Absorbs

- Realised flow-supply disruptions (current `geopolitics` scope).
- Future supply news / policy announcements (current `supply` fast component).
- Precautionary or geopolitical risk shocks (current `geopolitics`).
- Logistics / storage / conversion bottlenecks.
- Scheduled planned supply releases (was earmarked for the now-discarded `planned_supply_balance`).

### 3.4 Does NOT own

- Broad physical demand — `oil_demand_nowcast`.
- Inventory-level dynamics — `storage_curve`.
- Cross-asset / macro beta — `regime_classifier` (conditioning only, not alpha).

---

## 4. Deliverables

### 4.1 Desk implementation

Create `desks/supply_disruption_news/{__init__.py, desk.py, classical.py, spec.md}`. Delete the four legacy directories (see §1). Ridge-level classical head acceptable for Phase 2 scale-out; mechanism rebuild (two-stage hurdle / Bayesian event study / GBDT on structured event features) is a §7.3 escalation item under D1.

### 4.2 Event schema (internal)

Minimum fields the classical head should thread through:
- `event_class` ∈ {`realised_disruption`, `policy_announcement`, `precautionary_shock`, `logistics_bottleneck`, `demand_shock`}
- `event_timestamp`
- `region`
- `benchmark_exposure` (WTI / Brent / both)
- `novelty_score` (if upstream provides; optional)
- `source_reliability` (if upstream provides; optional)

### 4.3 State-conditioning (minimum)

At decision time the desk reads:
- spare-capacity proxy (OPEC quota − production)
- inventory-buffer proxy (`storage_curve`'s prompt-tightness state)
- curve state (prompt spread level)
- volatility / uncertainty regime (from `regime_classifier`)

### 4.4 Data-source feeds

Update `config/data_sources.yaml` so `supply_disruption_news` subscribes to:
- `eia_wpsr` (planned supply component)
- `opec_announcement`
- `cftc_cot` (positioning regime)
- any OFAC/HMT/EU sanctions feed
- scraped news (GPR-style)

Remove dangling references to the four deleted legacy desks.

### 4.5 Tests

Update or rewrite as needed:
- `tests/test_oil_redesigned_desks.py` — retarget fixtures to the new desk name.
- `tests/test_phase1_smoke.py`, `tests/test_phase1_round_trips.py` — update imports.
- `tests/test_logic_gate_multi_scenario.py` — change `DESK_NAMES_ORDERED` to the 3-desk oil roster (C7 of the plan).

---

## 5. Required design choices

- **Never emit outside activation.** The desk's default point_estimate is 0 unless an event is active. This is load-bearing for the "aggregate holds on ≥ 2/3" gate.
- **Use internal labels for training signal.** Train on auxiliary labels (`p_disruption`, `signed_barrel_impact`), map to emitted `WTI_FRONT_1W_LOG_RETURN` via a calibrated monotone link.
- **State conditioning is mandatory.** No "event class alone" forecasting — always condition on spare capacity, inventory, curve, uncertainty regime.

---

## 6. Minimum acceptance criteria

### Architectural
- Gate 3 runtime hot-swap passes via `eval.hot_swap.build_hot_swap_callables`.
- No shared-infra changes.

### Desk-definition
- Desk spec (`desks/supply_disruption_news/spec.md`) reflects the merged scope.
- Emitted target is `WTI_FRONT_1W_LOG_RETURN`.
- Internal auxiliary labels are documented and do not leak to the Controller.

### Model / evaluation
- Forecast differs across event classes.
- Forecast differs when market state changes.
- Evaluation matches the desk's real claim (conditional-sample evaluation for activation windows; no "dense daily forecaster" scoring).

### Evidence
- At least one test proving state-conditioning matters.
- At least one test proving class-specific logic matters.
- One falsification test that would fail if the desk were reduced to a generic event score.

---

## 7. Non-goals

- Full LLM event-extraction pipeline (Phase 3).
- Real data wiring (Phase 3).
- Optimising for existing v1.15 pinned seeds (they belong to the 5-desk roster; the 3-desk rebaseline happens in C12).
- Slow supply-response desk (optional Phase 3 per pasted review).

---

## 8. Questions the engineer must answer

1. What exact emitted target does the redesigned desk produce? (Expected: `wti_front_1w_log_return`.)
2. What event classes are implemented?
3. What state variables are used for conditioning?
4. How does the hurdle model map internal auxiliary labels to the emitted signed log-return?
5. What sparse-event evaluation strategy is used?
6. What falsification test would fastest prove the redesign is still wrong?

---

## 9. Success condition

A desk whose mechanism is economically coherent, whose input set is available at decision time, whose forecast depends on event class AND market state, whose evaluation matches its real claim (sparse-event-aware), and whose output composes cleanly under `controller/decision.py:94-112` raw-sum aggregation.
