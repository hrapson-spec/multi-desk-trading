# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Big picture

This is an **architecture-first** research repo, not a P&L-chasing repo. The deliverable is the orchestration machinery — contracts, bus, controller, attribution, research loop, evaluation harness. The architectural claim is "the shared machinery redeploys to an unrelated asset class (equity VRP) with zero changes to shared infrastructure" (§1.1, §8.4). Per-desk model quality is a capability signal, not the objective (§1.3.2). Negative results are deliverables (§1.3.4).

The authoritative specification lives at `docs/architecture_spec_v1.md`. Read the change-log at §0 to see current version and rules; PM artefacts at `docs/pm/{master_plan,raid_log,problem_log}.md` track active state. `docs/capability_debits.md` is the running debt ledger.

## Commands

```bash
# Setup (uv-managed venv already exists at .venv/)
.venv/bin/pip install -e '.[dev]'

# Full test suite (~20s)
.venv/bin/pytest tests/ -q

# Single test file
.venv/bin/pytest tests/test_logic_gate_multi_scenario.py -q

# Single test with diagnostic output
.venv/bin/pytest tests/test_logic_gate_multi_scenario.py::test_logic_gate_multi_scenario -v -s

# Lint / format (ruff line-length 100, target py311)
.venv/bin/ruff check .
.venv/bin/ruff format .

# Type check (strict for attribution/, contracts/, bus/, controller/,
# research_loop/, sim/, soak/; loose elsewhere)
.venv/bin/mypy .
```

Reliability-gate soak is a separate CLI: `.venv/bin/python scripts/run_soak_test.py --duration-extra-s 14400` (4h default).

## Frozen surfaces — DO NOT MODIFY without explicit approval

The architectural claim rests on these staying stable. Any change to §4, §6, §7, §8, §9, §10, or §11 of the spec requires a v2 bump and invalidates all prior tagged runs.

- `contracts/v1.py` — Pydantic schemas for `Forecast`, `Print`, `Grade`, `Decision`, `SignalWeight`, `ControllerParams`, `RegimeLabel`, `ResearchLoopEvent`. Append-only fields only.
- `contracts/target_variables.py` — frozen registry. Additions are v1.x revisions per §4.6 (not v2); removals are v2 bumps. Bus validator rejects any Forecast/Print whose `target_variable` is not in `KNOWN_TARGETS`.
- `controller/decision.py` — `Controller.decide` sums raw `weight × point_estimate` across `(desk, target)` pairs (§8.2). **Mixed-unit targets do not aggregate.** Desks in the same family emit one shared decision-space unit: `WTI_FRONT_1W_LOG_RETURN` (oil), `VIX_30D_FORWARD_3D_DELTA` (equity).
- `bus/`, `persistence/`, `eval/hot_swap.py`, `provenance/`, `scheduler/` — shared infra verified zero-diff under equity-VRP redeployment. Touching any of these may break the portability claim.

## Desk architecture

Desks are forecast-emitting components in `desks/`. Each desk implements the `DeskProtocol` in `desks/base.py` (a `runtime_checkable` Protocol, not a required parent class — `StubDesk` is provided as a convenient base).

Current v1.16 roster (as of 2026-04-22):
- **Oil (3 desks)**: `storage_curve`, `supply_disruption_news` (merged supply + geopolitics), `oil_demand_nowcast` (merged demand + macro alpha). All emit `WTI_FRONT_1W_LOG_RETURN`.
- **Equity-VRP (2 desks)**: `surface_positioning_feedback` (merged dealer_inventory + hedging_demand — reads all 4 legacy channels), `earnings_calendar` (event-driven). Both emit `VIX_30D_FORWARD_3D_DELTA`.
- **`regime_classifier`** — emits `RegimeLabel` (not Forecast), implements a different Protocol. Carries macro-beta transmission as of v1.16 (the standalone `macro` alpha desk was removed).

Per-desk files: `spec.md` (pre-registered claim), `desk.py` (Protocol impl), `classical.py` (ridge / composite ridge — deliberately modest per §1.3.2 Capability-before-P&L).

### Three hard gates (§7.1)

Every desk is evaluated against:

1. **Gate 1 — skill vs pre-registered naive baseline.** Price-targeted desks use `eval.data.random_walk_price_baseline`; return-targeted desks use `eval.data.zero_return_baseline`. Scale-consistent pairing is load-bearing.
2. **Gate 2 — dev → test sign preservation** (Kronos-RCA Spearman ρ stable across the split).
3. **Gate 3 — hot-swap.** `eval.hot_swap.build_hot_swap_callables` runs `Controller.decide()` with the real desk then a `StubDesk` swap, asserting `combined_signal` delta matches `-weight × point_estimate` and `contributing_ids` excludes retired/stubbed desks.

Gate 3 is the portability invariant (model-independent interface contract). Gate 1/2 are capability signals — weak results are **logged as capability debits** in `docs/capability_debits.md`, not treated as bugs.

## Simulator invariants

`sim/` (oil) and `sim_equity_vrp/` (equity) expose `LatentMarket.generate()` → `ObservationChannels.build()` paths. The equity sim enforces a seed-offset convention at `sim_equity_vrp/latent_state.py:21-27` that is **load-bearing for D12 golden-fixture tests**:

```
main stream     → seed         (vol_level, dealer_flow, spot)
regime sequence → seed + 1
hd latent       → seed + 2     (v1.13)
hd observation  → seed + 3     (v1.13, in observations.py)
earnings events → seed + 4     (v1.16 X1)
```

Adding new channels: use a new isolated RNG stream at `seed + 5+`, generate AFTER all existing draws, and verify the existing D12 hashes (`tests/test_sim_equity_vrp.py::test_dealer_inventory_golden_fixtures_unchanged`) remain byte-identical. Precedents that preserved D12: the `surface_positioning_feedback` merged-view (C9), `fair_vol_baseline` channel (C11), `earnings_calendar` channel (X1). Re-recording D12 is permitted under v1.x spec revisions but should be a deliberate choice, not incidental.

## Capability-debit discipline

The project tracks model-quality gaps as **named debits** (§1.3, §12.2 item 6) rather than silent failures. Open debits live in `docs/capability_debits.md`; decisions and strategic risks live in `docs/pm/raid_log.md`. When a test would otherwise silently weaken, open a D-decision in `raid_log.md` + a capability-debit entry instead.

A debit is in-budget if it is bounded, explicitly mitigated, and does not break the architectural claim. A debit that invalidates portability, controller correctness, or the frozen contract surface is **not in-budget** and blocks phase exit.

## Replay and provenance

Every emission carries a `Provenance` block with `code_commit` and `input_snapshot_hash` (§4.3). The bus has a `mode` flag: **production mode rejects any Forecast with `code_commit` ending in `-dirty`**. Development mode allows dirty-tree emissions with audit-log flagging. Replay-mode is a first-class operation — `grading.match.grade(forecast, print)` is a pure function; re-running on historical data reproduces grades byte-identically.

## Working conventions

- **Design-review pattern**: the owner runs a formal critic-first review on implementation plans (`design_review: REQUEST_CHANGES` with `blocking[]` and `major[]` findings). When such a review rejects a plan, integrate ALL blocking + major findings into a revised plan before the first commit. See decision D-11 in `raid_log.md` for the canonical example.
- **Additive-first restructures**: when reshaping the desk roster, new desks are added alongside legacy ones (e.g. `C4a/C5a/C8a`), and legacy deletion + test migration is batched into a dedicated cleanup wave (e.g. `W3..W8`). This keeps the test suite green at every commit boundary.
- **Commit messages**: conventional-commits style with `(C1/12)` style wave markers when shipping a planned sequence. Long bodies documenting mechanism, D-decisions affected, and test evidence are the norm — see recent commits on `wip-attribution-and-desk-models` for the pattern.
- **Spec version bumps**: a v1.x revision (append-only, non-breaking) logs a new row in `docs/architecture_spec_v1.md` §0 change log. The title at line 1 and the `master_plan.md` header should track the bump.

## What does not live here

- Live capital, paper backtesting against real data — Phase 3.
- Paid data feeds (Bloomberg, Argus, Platts, Kpler, Vortexa) — out of scope per §1.2.
- LLM in the trading decision path — banned per §13; LLMs live only in the research loop under §6.4 postcondition routing.
- CVaR / utility-theoretic / covariance-based sizing — deferred to Phase 2; Controller is linear per §8.2a.
