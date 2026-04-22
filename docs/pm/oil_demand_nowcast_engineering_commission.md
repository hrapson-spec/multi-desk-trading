# `oil_demand_nowcast` Desk — Engineering Commission

**Project**: multi-desk-trading
**Date issued**: 2026-04-22
**Status**: commissioned (stub), not yet implemented
**Audience**: engineer owning the oil demand-nowcast rebuild
**Authorising context**:
- `docs/first_principles_redesign.md` (adopted pasted review)
- `~/.claude/plans/the-architecture-is-already-unified-adleman.md` (C5)

---

## 1. Objective

Build the new oil `oil_demand_nowcast` desk that replaces two legacy directories (`desks/demand/` and `desks/macro/`). The macro alpha content is absorbed here; macro-as-alpha is removed (`macro` becomes regime-conditioning state via `regime_classifier`).

---

## 2. Problem statement

Per the pasted review:

- Current `demand` desk tries to behave like a short-horizon price forecaster despite its mechanism being a slower mixed-frequency nowcast problem.
- Current `macro` desk over-claims — it is really cross-asset conditioning, not a clean oil-specific desk.
- Both desks have inconsistent sign/spec/code + train/serve boundary issues.

---

## 3. Target redesign

### 3.1 Controller-facing emission

- `target_variable = "wti_front_1w_log_return"` (`contracts.target_variables.WTI_FRONT_1W_LOG_RETURN`)
- `point_estimate`: signed 1-week log-return contribution from the nowcast.
- Low confidence outside fresh-release windows.

### 3.2 Internal auxiliary labels

- `physical_demand_surprise_z` (primary)
- `refinery_run_surprise_z`
- Optional: deferred-strip residual over 5–20d as an internal target for falsification.

### 3.3 Feature groups

- Vintaged PMIs, refinery runs / utilisation.
- Refining margins / crack spreads.
- Mobility / throughput / port activity.
- Import / export / customs deltas.
- Release-age and revision metadata.

### 3.4 Absorbs

- Current `demand` desk scope in full.
- Current `macro` desk's demand-transmission alpha content.

### 3.5 Does NOT own

- Scheduled supply / event-driven disruption — `supply_disruption_news`.
- Cross-asset macro beta — `regime_classifier` (conditioning only).

---

## 4. Deliverables

### 4.1 Desk implementation

Create `desks/oil_demand_nowcast/{__init__.py, desk.py, classical.py, spec.md}`. Delete `desks/demand/` and `desks/macro/`. Ridge-level classical head acceptable for Phase 2 scale-out; mixed-frequency state-space / dynamic-factor nowcast is a §7.3 escalation under D1.

### 4.2 Train / serve boundary

- Train only on features available before the decision timestamp.
- Use explicit release-lag handling (no leakage via monthly revisions).
- Widen uncertainty when only stale slow-moving data is available.

### 4.3 Data-source feeds

Update `config/data_sources.yaml` to route demand feeds to the new desk and remove references to `desks/demand/` and `desks/macro/`.

### 4.4 Tests

- `tests/test_classical_specialists.py` — replace demand/macro test cases with `oil_demand_nowcast`.
- `tests/test_horizon_matching.py` — update.
- `tests/test_phase1_smoke.py`, `tests/test_phase1_round_trips.py` — update imports.

---

## 5. Minimum acceptance criteria

- Gate 3 runtime hot-swap passes.
- Desk spec reflects mixed-frequency nowcast mechanism and the cross-asset-absorption boundary.
- Emitted target is `WTI_FRONT_1W_LOG_RETURN`; internal labels do not leak to Controller.
- Evaluation is vintaged-release-aware (not dense daily).

---

## 6. Non-goals

- Full mixed-frequency state-space nowcast (Phase 2 follow-on under D1 escalation).
- Real macro-release data wiring (Phase 3).
- Optimising for v1.15 pinned seeds (pre-restructure roster).

---

## 7. Questions the engineer must answer

1. What vintaged features does the desk read at decision time?
2. How is the "update days only" evaluation mode implemented?
3. What forces the desk to low-confidence behaviour when only stale data is available?
4. What falsifier would most quickly show the nowcast is a leakage artefact?

---

## 8. Success condition

A desk that (a) emits near-zero high-confidence forecasts outside fresh-release windows, (b) produces a signed 1-week return contribution that is monotone in the nowcast-surprise auxiliary label, and (c) composes cleanly under raw-sum aggregation alongside `storage_curve` and `supply_disruption_news`.
