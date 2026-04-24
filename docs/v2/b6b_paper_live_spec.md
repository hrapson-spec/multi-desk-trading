# B6b paper-live loop specification

**Status**: accepted baseline, tag `v2-b6b-paper-live-0.1`  
**Created**: 2026-04-24  
**Slice**: v2 Phase B, immediately after B6a  
**Depends on**: B6a execution primitives (`control_law`, `adapter`, `degradation`)  
**Primary code targets**: `v2/execution/simulator.py`, `v2/paper_live/loop.py`, `v2/runtime/kill_switch.py`

## 1. Purpose

B6b turns the B6a pure execution primitives into a replayable, stateful paper-live loop.

The output is **not** a promotion to S4 shadow-live. It is the software substrate that later makes S4 possible:

- one deterministic daily decision tick;
- one internal-simulator fill path;
- one append-only decision and execution ledger;
- kill-switch precedence before desk forecast requests;
- enough snapshot/replay discipline to test operational validity later.

B6b is infrastructure. It produces no model-quality claim and no live-capital capability.

## 2. Slice boundary

### In scope

- Single family: `oil_wti_5d`.
- Single desk initially: `prompt_balance_nowcast`.
- Daily/EOD tick orchestration invoked by a caller, not a daemon.
- Internal simulated fills only; no broker API.
- Optimistic and pessimistic cost scenarios on every tick.
- Runtime state persisted outside the PIT store.
- Minimal kill-switch reader and default enabled state.
- Snapshot receipt after each successful tick.
- Unit and integration tests for deterministic replay, kill-switch precedence, and ledger persistence.

### Out of scope

- Real scheduler daemon / cron wrapper.
- `killctl` CLI and full automated `KS-*` rule engine.
- Replay-from-snapshot restore command.
- External alerts.
- Real broker, exchange, or order-routing adapter.
- Multi-family orchestration.
- Any S1/S2/S3/S4 promotion decision.

## 3. Required architecture

B6b has three layers.

| Layer | Module | Responsibility |
|---|---|---|
| Pure tick orchestration | `v2/paper_live/loop.py::run_decision_tick` | Convert explicit tick inputs into a `DecisionV2`, `ExposureState`, lot target, and scenario ledger rows. No hidden wall-clock, random IDs, or filesystem reads. |
| Stateful loop driver | `v2/paper_live/loop.py::PaperLiveLoop` | Read kill-switch, build `FeatureView`s, call desks, call `run_decision_tick`, persist rows, update exposure state. |
| Runtime persistence | `v2/execution/simulator.py` | Own append-only runtime DuckDB tables, deterministic IDs, latest-state reads, and snapshot receipts. |

The PIT store remains read-only during B6b. Runtime state lives under a separate `runtime_root`, e.g. `data/runtime/paper_live.duckdb`, not in `pit.duckdb`.

## 4. Tick flow

For each eligible decision timestamp:

1. **Read kill-switch state** from `runtime_root/kill_switch.yaml`.
2. **Short-circuit before desks** if system/family state is `frozen` or `halted`.
3. **Build feature views** for non-isolated desks using the PIT reader.
4. **Ask desks for `ForecastV2`** with explicit `emitted_ts`, `prereg_hash`, `code_commit`, `contract_hash`, and `release_calendar_version`.
5. **Synthesise family forecast** using `synthesise_family`.
6. **Compute `b_t`** using B6a `compute_target_risk_budget`.
7. **Advance degradation state** using B6a `step`.
8. **Create `DecisionV2`** for the economic decision:
   - if family forecast is valid: `abstain=False`, `target_risk_budget=b_t`, `degradation_state=healthy`;
   - if family abstains or kill-switch blocks: `abstain=True`, `target_risk_budget=None`, non-healthy degradation state.
9. **Map effective exposure to lots** using B6a `target_lots`.
10. **Apply optimistic and pessimistic costs** using `v2.eval.cost_model`.
11. **Persist** one family-decision row and two execution-ledger rows.
12. **Write snapshot receipt** over runtime rows + PIT manifest hash + kill-switch state.
13. **Update in-memory exposure state** for the next tick.

## 5. Kill-switch semantics

B6b implements a minimal read-only kill-switch.

| Runtime state | Desk calls? | Family forecast | Degradation event | Effective exposure |
|---|---|---|---|---|
| `enabled` | Yes, except isolated desks | Normal synthesis | Normal B6a ladder | From ladder |
| desk `desk_isolated` | No for that desk | Synthesis over remaining desks; if none remain, family abstains | Normal abstain ladder | Hold/decay per ladder |
| family `frozen` / `halted` | No | Synthetic family abstain with `kill_switch:<reason>` | `kill_switch_halting=True` | Force flat through `HARD_FAIL` |
| system `frozen` / `halted` | No | Synthetic family abstain with `kill_switch:<reason>` | `kill_switch_halting=True` | Force flat through `HARD_FAIL` |

B6b follows the committed B6a semantics: any kill-switch halting state maps to `HARD_FAIL` and target `0.0`. If a later decision wants a gradual family-level decay on `frozen`, that is a B6a contract change and must be handled before modifying B6b.

If `kill_switch.yaml` is absent, B6b creates or assumes:

```yaml
system_state: enabled
families:
  oil_wti_5d:
    state: enabled
    isolated_desks: []
    reason: ""
```

## 6. Persistence model

### 6.1 Runtime database

`InternalSimulator.open(runtime_root)` opens:

```text
runtime_root/
  paper_live.duckdb
  kill_switch.yaml
  snapshots/
```

The runtime DB is append-only for normal operation. Updates are permitted only for internal schema migrations before B6b is tagged.

### 6.2 `family_decisions`

One row per family per decision tick.

Required fields:

| Field | Notes |
|---|---|
| `decision_id` | Deterministic content-addressed ID, `dec_<sha16>`. |
| `family` | `oil_wti_5d` at v2.0. |
| `decision_ts` | Economic decision timestamp. |
| `emitted_ts` | Explicitly supplied tick emission timestamp. |
| `decision_json` | Canonical `DecisionV2.model_dump_json()` payload. |
| `decision_hash` | SHA-256 over canonical decision JSON. |
| `family_forecast_hash` | SHA-256 over canonical `FamilyForecast` payload, including synthetic abstain payloads. |
| `forecast_ids_json` | JSON list of contributing or abstaining `ForecastV2.forecast_id`s. |
| `kill_switch_json` / `kill_switch_hash` | Effective state read before desk calls, plus SHA-256 over canonical state JSON. |
| `created_at` | UTC wall-clock write time; not included in deterministic IDs. |

Uniqueness: `(family, decision_ts)`.

### 6.3 `execution_ledger`

Two rows per decision tick: optimistic and pessimistic.

Required fields:

| Field | Notes |
|---|---|
| `execution_id` | Deterministic content-addressed ID, `exec_<sha16>`, over canonical execution-row content excluding `created_at`. |
| `decision_id` | FK-like reference to `family_decisions.decision_id`. |
| `scenario` | `optimistic` or `pessimistic`. |
| `prior_target` / `new_target` | Effective risk-budget target before/after degradation. |
| `prior_lots` / `new_lots` | Simulator-maintained lot state before/after this tick. |
| `raw_lots` / `effective_b` | Adapter diagnostics. |
| `price` / `market_vol_5d` | Market inputs used by adapter. |
| `gross_return` / `fill_cost` / `net_return` | Scenario PnL fields. |
| `degradation_state` | `healthy`, `soft_abstain`, `aged`, or `hard_fail`. |
| `abstain` / `abstain_reason` | Mirrors `DecisionV2` semantics. |
| `created_at` | UTC wall-clock write time; not included in deterministic IDs. |

Uniqueness: `(family, decision_ts, scenario)`.

`prior_lots` is maintained by the loop from the previous tick and seeded from the latest optimistic runtime ledger row on loop construction. It must not be hard-coded by an external caller.

## 7. Determinism requirements

B6b must be replayable.

- `run_decision_tick` receives `decision_ts` and `emitted_ts`; it must not call `datetime.now()`.
- Runtime row IDs are content-addressed, not UUID-based.
- Canonical JSON uses sorted keys and stable timestamp formatting.
- Running the same tick twice against a fresh runtime DB produces identical `decision_id`, `decision_hash`, and `execution_id`s.
- Duplicate tick insertion is rejected or treated as idempotent only if the hashes match exactly.
- `created_at` is allowed to differ across replays but is excluded from all deterministic hashes.
- The PIT store is never mutated by the paper-live loop.

## 8. Snapshot receipt

After each successful tick, B6b writes a lightweight snapshot receipt:

```text
runtime_root/snapshots/<decision_ts>/
  receipt.json
  receipt.sha256
```

`receipt.json` includes:

- latest `decision_id`;
- the two `execution_id`s;
- PIT manifest hash or manifest id set used by contributing forecasts;
- kill-switch state hash;
- git/code commit;
- contract hash;
- runtime DB row counts for `family_decisions` and `execution_ledger`.

B6b does not implement full restore. It only creates receipts that later B7/B8 restore tests can consume.

## 9. Tests

Minimum test pack:

| Test file | Required coverage |
|---|---|
| `tests/v2/execution/test_simulator.py` | Runtime DB bootstrap, append-only inserts, latest-state reads, deterministic IDs, duplicate tick behaviour. |
| `tests/v2/paper_live/test_run_decision_tick.py` | Pure tick: valid forecast, family abstain, soft abstain, aged/TTL path, hard fail, two cost scenarios. |
| `tests/v2/paper_live/test_loop.py` | Stateful driver builds feature views, calls desks, persists one decision + two ledger rows, updates exposure state. |
| `tests/v2/paper_live/test_kill_switch.py` | Kill-switch is read before desks; halted/frozen states do not call desks and force flat. |
| `tests/v2/paper_live/test_replay.py` | Same inputs in a fresh runtime DB reproduce deterministic IDs and hashes. |

Existing B6a tests must remain green:

```bash
uv run pytest tests/v2/execution -q
```

B6b acceptance requires:

```bash
uv run pytest tests/v2/execution tests/v2/paper_live -q
```

## 10. Acceptance criteria

B6b is complete when:

- `v2/execution/simulator.py` persists deterministic family-decision and execution-ledger rows.
- `v2/paper_live/loop.py::run_decision_tick` is pure and fully covered.
- `PaperLiveLoop.tick(...)` runs a single-family paper-live tick end-to-end against a PIT reader and desk registry.
- Kill-switch `frozen` / `halted` prevents desk forecast calls and forces `HARD_FAIL`.
- Desk isolation skips the isolated desk before synthesis.
- Two scenario rows are recorded per tick with distinct cost results when cost assumptions differ.
- Snapshot receipt is written after successful persistence.
- Replaying identical inputs into a fresh runtime root reproduces deterministic IDs and hashes.
- No B6b code uses v1 simulator outputs as promotion or decision evidence.
- No real broker or live-capital pathway exists.

## 11. Implementation order

1. Add `v2/runtime/kill_switch.py` with default-enabled reader and tests.
2. Replace UUID-based runtime IDs with content-addressed deterministic IDs in `InternalSimulator`.
3. Add `family_decisions` persistence before `execution_ledger`.
4. Make `run_decision_tick` pure: remove hidden wall-clock calls and return `DecisionV2`.
5. Teach `PaperLiveLoop` to inject `emitted_ts`, read kill-switch first, and skip isolated desks.
6. Add snapshot receipt writer.
7. Add replay test over a fresh runtime root.
8. Run B6a + B6b test pack.

## 12. Design checks before coding

Resolve or explicitly document these before tagging B6b:

- **Desk protocol signature**: `DeskV2.forecast` should include the B3b runtime fields used by `PromptBalanceNowcastDesk` (`contract_hash`, `release_calendar_version`, `emitted_ts`) or the loop should call only the protocol-minimum signature.
- **TTL semantics**: B6a currently treats TTL breach as `HARD_FAIL`; older paper contract prose also mentions aged decay beyond TTL. B6b follows B6a unless the contract is revised.
- **Decision vs exposure semantics**: `DecisionV2` records economic action or abstention; `execution_ledger` records effective exposure after degradation. Do not force degraded exposure into `DecisionV2.target_risk_budget`.
- **Runtime DB location**: confirm `runtime_root/paper_live.duckdb` as separate from the PIT store before implementation.
