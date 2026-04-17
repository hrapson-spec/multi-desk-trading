# Week 0 Scaffold — Build Plan

**Status**: Plan frozen 2026-04-17. Execution starts Day 1.
**Spec reference**: `docs/architecture_spec_v1.md` v1.2.
**Budget**: ≤ 6 weeks calendar (abandon-criterion 3, §12.3). Realistic target: 4 weeks.
**Done-criterion**: all Week 0 artefacts green under `pytest -q`, `mypy --strict contracts/`, `ruff check .`, and the two load-bearing tests (`test_boundary_purity.py`, `test_replay_determinism.py`) pass.

---

## 1. Context

Under spec §12.1, Week 0 is the scaffold phase: nothing desk-specific, nothing trading-specific. The deliverable is orchestration machinery that can accept six-stub desks in Weeks 1–2 without rework. Scaffold completion is a gate — no desk work until it is green. Scaffold overrun (> 6 weeks) triggers Phase 1 abandon.

Capability claim being established at Week 0: the contract boundary is enforceable, the bus rejects malformed events, the persistence layer replays byte-identically, and the grading harness matches Forecast ↔ Print via the event-horizon rules (§4.7).

---

## 2. Artefacts

Ten modules / test files. All live under the repo root.

| # | Artefact | Role | LOC target |
|---|---|---|---|
| 1 | `contracts/v1.py` | Pydantic v2 types per spec §4.3 | ~150 |
| 2 | `contracts/target_variables.py` | Frozen registry (**done at v1.1**) | 53 |
| 3 | `contracts/__init__.py` | Re-exports public API | ~20 |
| 4 | `bus/bus.py` | Synchronous in-memory dispatcher with validation | ~120 |
| 5 | `bus/__init__.py` | Public API | ~10 |
| 6 | `persistence/schema.sql` | 10-table DuckDB schema | ~150 |
| 7 | `persistence/db.py` | Connection management, point-in-time query helpers | ~100 |
| 8 | `grading/match.py` | Forecast × Print matching per §4.7 + Grade emission | ~120 |
| 9 | `scheduler/calendar.py` | Release-calendar scheduler (cron-style) | ~80 |
| 10 | `provenance/hash.py` | Input-snapshot hasher + code_commit resolver | ~60 |
| 11 | `tests/test_boundary_purity.py` | Load-bearing: Controller runs against stubs | ~100 |
| 12 | `tests/test_replay_determinism.py` | Load-bearing: byte-identical replay | ~100 |
| 13 | `tests/test_bus_validation.py` | Registry + dirty-tree rejection | ~80 |
| 14 | `tests/test_horizon_matching.py` | Event + clock horizon matching | ~80 |
| 15 | `tests/test_persistence.py` | Schema round-trip, replay queries | ~60 |
| 16 | `tests/conftest.py` | Shared fixtures (synthetic calendar, stub desks) | ~80 |

Total: ~1,360 LOC across 16 files. 4 weeks of solo work is feasible at ~350 LOC/week average; headroom for debugging is built in.

---

## 3. Build sequence (dependency-ordered)

Each step depends only on prior steps, so any step can be wholly completed and tested before the next begins.

1. **`contracts/v1.py`** → everything else imports from here. Start with Pydantic models and `ResearchLoopEvent.event_type` literal; validate via roundtrip tests (`model_dump()` → `model_validate()`).
2. **`persistence/schema.sql` + `persistence/db.py`** → defines the DB shape the bus needs. Include migration function `init_db(path: Path) -> None` that runs the schema idempotently.
3. **`bus/bus.py`** → uses contracts for typing; uses persistence for writes. The bus is where the three validations land: target-registry check, dirty-tree check (mode-dependent), event schema validation (automatic via Pydantic).
4. **`grading/match.py`** → uses contracts + persistence. Implements the §4.7 matching function with per-desk tolerance support. Emits Grade events via the bus.
5. **`scheduler/calendar.py`** → uses bus. Registers scheduled triggers from a config file; fires them at mock "now" times for testing.
6. **`provenance/hash.py`** → standalone utility module. Used by scaffold tests and later by desks.
7. **Tests** — each test file drops in as its dependencies come online. `test_boundary_purity.py` is the capstone: it depends on all modules above and asserts the end-to-end pipeline runs against stubs without importing any desk's internals.

---

## 4. Design commits (from v1.2 spec + this round)

| Decision | Source |
|---|---|
| DuckDB: single file `data/duckdb/main.duckdb` with all 10 tables | Spec v1.2 §3.2 |
| Bus: synchronous in-memory dispatcher (upgrade path via interface) | This round |
| Scheduler: cron-style Python scheduler; Prefect deferred (§3.3) | Spec §3.3 |
| Test framework: pytest | pyproject.toml |
| Type strictness: `mypy --strict` on `contracts/` and `bus/`; loose elsewhere | This round |
| Plan doc location: `docs/plans/week0_scaffold.md` (in-repo) | This round |
| Event-horizon match function: implemented once in `grading/match.py`; reused everywhere | Spec §4.7 |
| Dirty-tree policy: bus mode flag (development / production) per §3.1 | Spec v1.1 |

---

## 5. Per-module specifications

### 5.1 `contracts/v1.py`

Direct translation of the Python block in spec §4.3. One file, no submodules. Every class has `model_config = ConfigDict(frozen=True)`.

Key invariants to enforce at model level (Pydantic validators):
- `Forecast.target_variable` must be in `contracts.target_variables.KNOWN_TARGETS`.
- `Forecast.emission_ts_utc.tzinfo is not None` (no naive timestamps).
- `EventHorizon.expected_ts_utc.tzinfo is not None`.
- `UncertaintyInterval.lower ≤ upper`.
- `DirectionalClaim.sign == "none"` ⇒ stub only (flagged via Forecast `provenance.model_name`-prefix convention "stub_"; enforced at bus, not model).

`ResearchLoopEvent.event_type` must include all 9 triggers from §6.2 including `data_ingestion_failure` and `periodic_weekly`.

### 5.2 `contracts/target_variables.py`

**Already shipped at v1.1.** Registry contains `WTI_FRONT_MONTH_CLOSE`. No Week 0 changes.

### 5.3 `bus/bus.py`

One class, `Bus`, with the following interface:

```python
class Bus:
    def __init__(self, db: Database, mode: Literal["development", "production", "replay"]): ...
    def publish_forecast(self, f: Forecast) -> None: ...
    def publish_print(self, p: Print) -> None: ...
    def publish_decision(self, d: dict) -> None: ...
    def publish_grade(self, g: Grade) -> None: ...
    def publish_signal_weight(self, w: SignalWeight) -> None: ...
    def publish_regime_label(self, r: RegimeLabel) -> None: ...
    def publish_research_event(self, e: ResearchLoopEvent) -> None: ...
    def subscribe(self, event_type: type, handler: Callable) -> None: ...
```

Validation rules executed on every `publish_*` (in order):
1. Pydantic model validation (automatic on type-annotated publish).
2. `Forecast.target_variable in KNOWN_TARGETS` (registry check).
3. `Forecast.provenance.code_commit` does NOT end with `"-dirty"` iff mode ∈ {production, replay}.
4. If valid → persist to DB → notify subscribers synchronously.
5. If invalid → raise `BusValidationError` with reason; never persist.

No async, no queue, no topics. Single-threaded call-chain. Simple enough to reason about during replay.

### 5.4 `persistence/schema.sql`

Single file, ten `CREATE TABLE` statements matching spec §3.2. All tables have primary keys on their ID columns and the indexes spec'd in §3.2.

Critical:
- `forecasts.horizon_type TEXT CHECK (horizon_type IN ('clock', 'event'))`.
- `forecasts.horizon_payload JSON` (stores the tagged-union body).
- `decisions.input_forecast_ids JSON` (array of strings; DuckDB supports JSON arrays).
- All timestamp columns use `TIMESTAMP WITH TIME ZONE`.
- `provenance` stored as JSON blob in each table that has it, rather than normalised (six different tables reference provenance; inline JSON is simpler than a separate `provenance` table joined everywhere).

### 5.5 `persistence/db.py`

Thin wrapper around `duckdb.connect()`. Functions:
- `init_db(path)` — runs schema idempotently.
- `insert_forecast(conn, f)` — typed insert.
- Plus `insert_*` per event type.
- `get_forecast(conn, forecast_id)` — returns Pydantic model.
- `replay_forecasts(conn, start_ts, end_ts)` — iterator over Forecasts in a time window.
- `point_in_time_snapshot(conn, as_of_ts)` — returns all events that existed at `as_of_ts` (key for replay determinism).

### 5.6 `grading/match.py`

One function, `grade(forecast, print) -> Grade | None`, implementing §4.7 match logic:

```python
def matches(forecast: Forecast, p: Print, tolerance_seconds: float = 21600) -> bool:
    if forecast.target_variable != p.target_variable:
        return False
    if forecast.horizon.kind == "event":
        return p.event_id == forecast.horizon.event_id
    # clock
    expected = forecast.emission_ts_utc + forecast.horizon.duration
    return abs((p.realised_ts_utc - expected).total_seconds()) <= tolerance_seconds
```

And a main loop `grade_all(db, forecasts_to_grade)` that scans pending-grade forecasts, finds matching prints, computes squared_error / absolute_error / sign_agreement / within_uncertainty / schedule_slip_seconds, and emits `Grade` events.

### 5.7 `scheduler/calendar.py`

Simple: a YAML-backed cron-style scheduler. Config at `config/release_calendar.yaml` listing the events from spec §3.3. Each entry has `event_id`, `cron_expr` (or similar), and `emission_offset` (forecasts emit this long before the event).

Scheduler runs as a long-lived process in production, but for Week 0 it is driven by a synthetic clock — `scheduler.advance_to(ts)` fires all triggers whose scheduled time is ≤ ts. This makes every scheduler action deterministic and replayable.

### 5.8 `provenance/hash.py`

Two functions:

```python
def hash_input_snapshot(inputs: Sequence[Any]) -> str: ...
def resolve_code_commit(mode: Literal["development", "production", "replay"]) -> str: ...
```

`hash_input_snapshot` uses SHA-256 of a canonicalised JSON representation of the input sequence. `resolve_code_commit` shells out to `git rev-parse HEAD` and checks `git status --porcelain`; appends `"-dirty"` if the working tree has uncommitted changes. In production mode, raises if dirty.

---

## 6. Test strategy

### 6.1 `tests/test_boundary_purity.py` — load-bearing

The single highest-leverage test. Imports only:

```python
from contracts.v1 import ...
from contracts.target_variables import KNOWN_TARGETS
from bus.bus import Bus
from persistence.db import init_db, get_forecast, replay_forecasts
from grading.match import grade_all
```

No imports from any `desks/` submodule (none exist yet; this asserts that none are needed). Uses synthetic stub "desks" defined inline as closures that emit valid `Forecast` objects.

Structure:
1. Spin up a temporary DuckDB file.
2. Initialise schema.
3. Instantiate the bus.
4. Register six stub desks that emit degenerate Forecasts (`directional_claim.sign="none"`, zero-width uncertainty, `point_estimate=0.0`).
5. Drive the scheduler over a synthetic 2-week calendar.
6. Let prints land (synthetic).
7. Run grade_all.
8. Assert: Controller skeleton (when built in Weeks 7+; for Week 0, a `controller_stub` that picks uniform weights) runs to completion with no exceptions.
9. Assert: attribution DB has zero meaningful contribution from any desk (all stubs; expected).
10. Assert: no module under `desks/` was imported during the run (via `sys.modules` check).

### 6.2 `tests/test_replay_determinism.py` — load-bearing

Golden-file test. Runs a seeded synthetic scenario twice and asserts byte-identical outputs:
1. Seed: fixed NumPy random seed = 42; fixed synthetic calendar; fixed stub desk outputs.
2. Run 1: capture all events written to DuckDB via `replay_forecasts` + similar; serialise to a canonical JSON.
3. Run 2: same seed, fresh DuckDB; same events.
4. Assert canonical-JSON output is byte-identical.

A change that breaks replay (non-determinism, clock-dependent logic, float ordering) shows up as a test failure, not as a silent drift in the attribution DB months later.

### 6.3 Supporting tests

- `test_bus_validation.py`: asserts bus rejects unknown target, dirty code_commit in production, naive timestamps.
- `test_horizon_matching.py`: asserts clock and event matches fire correctly; asserts event-slip is recorded in `Grade.schedule_slip_seconds`.
- `test_persistence.py`: roundtrip a Forecast through `insert_forecast` + `get_forecast`; replay-window query returns events in chronological order.
- `conftest.py`: shared fixtures for synthetic calendar, stub desks, temp DB.

### 6.4 Quality gates (CI-or-equivalent)

```
pytest -q                          # all tests pass
mypy --strict contracts/ bus/      # strict typing on contract surface
ruff check .                        # linting
ruff format --check .               # formatting
```

No linting-debt shipped. All four green before Week 0 is declared done.

---

## 7. Timeline — 4-week target, 6-week abandon

| Week | Focus | Exit condition |
|---|---|---|
| 0.1 | `contracts/v1.py` + its unit tests; `conftest.py` scaffolding | `pytest tests/test_contracts.py` green; `mypy --strict contracts/` green |
| 0.2 | `persistence/` + `test_persistence.py` | Insert/query roundtrip green; schema loads into a fresh DB |
| 0.3 | `bus/bus.py` + `test_bus_validation.py` | Bus rejects malformed, persists valid; dirty-tree rejection works |
| 0.4 | `grading/match.py` + `test_horizon_matching.py`; `scheduler/calendar.py`; `provenance/hash.py` | All three integrate; match function passes both clock and event tests |
| 0.5 | `test_boundary_purity.py` + `test_replay_determinism.py` integration | Both load-bearing tests green end-to-end |
| 0.6 | Buffer: address any integration fragility; documentation tidy; final CI green | All quality gates (§6.4) green; scaffold accepted |

---

## 8. Scope-cut ladder (if running long, per §14.1)

Engaged in order if Week 5 arrives without scaffold green:

1. **Cut `test_replay_determinism.py`.** Move to Week 1 as part of stubs-phase. Keep `test_boundary_purity.py`.
2. **Cut automated `scheduler/calendar.py`.** Replace with a manual pytest fixture that drives a synthetic calendar in each test. Real scheduler moves to Week 1.
3. **Cut `provenance/hash.py` as a separate module.** Inline the hash function directly in `bus/bus.py`; code-commit resolution becomes a one-line subprocess call.
4. **Cut `test_bus_validation.py` + `test_horizon_matching.py`.** Rely on `test_boundary_purity.py` to exercise validation paths and matching indirectly. Lose per-rule coverage; gain ~150 LOC.
5. **Cut `bus/` as a class.** Collapse to a set of module-level `publish_*` functions that validate + persist, without the subscribe/dispatch layer. Subscribers call persistence directly. Loses future-proofing but is smaller.

Never cut:
- `contracts/v1.py` (foundation for everything)
- Target-registry enforcement (the whole point of §4.6)
- Schema init (replay depends on it)
- `test_boundary_purity.py` (the load-bearing test that makes v1.2 portability claim testable)

---

## 9. Verification — scaffold-green definition

Scaffold is declared green (Week 0 done) iff all of the following:

- [ ] `pytest -q` passes with zero failures, zero errors.
- [ ] `mypy --strict contracts/ bus/` passes with zero errors.
- [ ] `ruff check .` passes with zero issues.
- [ ] `ruff format --check .` passes (no formatting drift).
- [ ] `test_boundary_purity.py` passes; manually verify no `desks.*` module is imported during the test.
- [ ] `test_replay_determinism.py` passes twice consecutively with byte-identical output.
- [ ] `persistence/db.py` can initialise a fresh `main.duckdb` containing all 10 tables from a clean directory.
- [ ] `bus.publish_forecast(malformed_forecast)` raises `BusValidationError`; no row lands in `forecasts` table.
- [ ] `contracts.v1.Forecast` with `target_variable="typo_here"` is rejected at bus validation (not at model validation — the registry check lives in the bus).
- [ ] README updated to check the first box in its Status section.

Upon all boxes checked: tag `scaffold-v1.0`. Proceed to Week 1 (stubs).

---

## 10. Open questions / risks

### 10.1 DuckDB concurrency model

DuckDB is single-writer; concurrent writers must serialise via a connection lock. Phase 1 is single-process-single-threaded, so this is not an issue. If the bus upgrades to threaded later, persistence needs a connection pool or a single-writer thread. Not Week 0 scope; flagged for Week 1+ if it matters.

### 10.2 Synthetic calendar under `pytest` vs a real scheduler process

`test_boundary_purity.py` drives time synthetically via the scheduler's `advance_to()` API. The real scheduler (running as a long-lived process post-scaffold) is not exercised by Week 0 tests. A separate smoke test `test_scheduler_live.py` that runs the scheduler for 60 seconds against a toy calendar could be added; deferred unless Week 0 runs light.

### 10.3 `subprocess.run(["git", "..."])` inside `resolve_code_commit`

Subprocess call per emission is a measurable cost at high-frequency emissions. Phase 1 daily/weekly cadence makes this negligible. If cadence increases to minute-level, cache the resolved commit per process-start. Flagged; not Week 0 blocker.

### 10.4 Event-horizon matching with vintage revisions

A Print may be revised (`vintage_of` != None). If a Forecast was graded against the original Print, and a revised Print lands, should the Grade re-fire? Spec §3.1 implies yes (re-grading is a pure function of the latest vintage), but the mechanism for revisiting existing Grades isn't in the v1.2 spec. Defer decision to Week 1 regime-classifier build; flag as a Phase 1 v1.x open.

### 10.5 Capability-claim debit tracking

Spec mentions "capability-claim debits" as a logged artefact but no schema exists for them yet. For Week 0 they can live as a markdown log at `docs/debits.md`; formalise to a table in Phase 2 if the list grows beyond trivial.

---

## 11. Out of scope for Week 0

- Any desk implementation (Weeks 1–2 and beyond).
- Any model training or inference.
- The actual research-loop LLM integration (Week 1+).
- The HDP-HMM regime classifier (end of Phase 1).
- Real data feeds (Weeks 1+ when first real desk deepens).
- CVaR sizing (Phase 2).
- Equity-VRP port (Phase 2).
- Observability beyond pytest + stdout logging; dashboards deferred.

---

## 12. Sign-off

| Field | Value |
|---|---|
| Plan version | v1.0 |
| Date frozen | 2026-04-17 |
| Spec reference | v1.2 |
| Execution starts | Day 1 post-sign-off |
| Expected completion | 4 weeks (target) / 6 weeks (abandon trigger) |
| First artefact | `contracts/v1.py` |
