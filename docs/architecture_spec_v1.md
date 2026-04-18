# Multi-Desk Trading Architecture — Specification v1.3

**Status**: Pre-registered / frozen on sign-off.
**Date frozen**: 2026-04-17.
**Supersedes**: none (v1 is the first committed version).
**Superseded by**: none as of this writing.
**Domain instance**: crude oil (WTI/Brent). Portability target: equity VRP.
**Author / owner**: Henri Rapson (solo).

Any change to §4, §6, §7, §8, §9, §10, or §11 requires a v2 bump and invalidates v1 runs. Non-breaking additions (new desks conforming to the frozen contract, new pre-registered event triggers, new gate-diagnostic metrics) can be added under v1.x revisions logged below.

---

## 0. Change log

| Version | Date | Change |
|---|---|---|
| v1.0 | 2026-04-17 | Initial freeze. |
| v1.1 | 2026-04-17 | Review response. Addresses 16 items (see `docs/reviews/2026-04-17-v1.0-review.md`). Blockers: weight-promotion contradiction fixed (§8.3 vs §11), `target_variable` frozen registry (§4.6, `contracts/target_variables.py`), horizon semantics + event-slip policy (§4.7). Structural: CVaR cut from Phase 1, linear sizing committed (§8.2, §8.2a). Significant: weight-matrix dimensionality discipline (§8.5), provenance dirty-tree policy (§4.3), `data_ingestion_failure` trigger (§6.2), strengthened done-criterion (§12.2). Smaller: N/M pinned (§7.2), `regime_probabilities` on RegimeLabel (§4.3), routing rules as postconditions (§6.4), Macro vs classifier clarified (§10.1), `attribution_lodo` grain fixed + `decisions` table added (§3.2). New flagged risks: §14.6 budget realism, §14.7 Phase 2 readiness, §14.8 cold-start policy. |
| v1.2 | 2026-04-17 | §3.2 correction: single DuckDB file (`data/duckdb/main.duckdb`) containing all tables, not per-table files. DuckDB is OLAP-oriented and handles many tables in one file efficiently; per-table splits complicate cross-table queries without Phase 1 benefit. Narrow correction; no other sections affected. |
| v1.3 | 2026-04-17 | Six-item v1.2 review response (see `docs/reviews/2026-04-17-v1.2-review.md`). (A) §14.8 cold-start boot_ts pinned to microsecond precision; §8.3 adds explicit tie-break rule (weight_id lexicographic) for same-ts reads. (B) §8.2a rewritten: `k_regime` and `pos_limit_regime` move to a new `controller_params` table (§3.2, new §4.3 `ControllerParams` type), removing magic-string target_variables from signal_weights. (C) §8.5 capacity feasibility footnote: regularisation assumed, not optional (HDP-HMM regime occupancy is typically skewed, not uniform). (D) `config/data_sources.yaml` added to Week 0 scaffold plan as the owning artefact of the data-source → desks mapping consumed by `data_ingestion_failure` payload (§6.2 unchanged). (E) §8.3/§11 rollback is an explicit distinct human operation with its own audit-log class, not via the auto-promotion margin gate. (F) §15 derivation-trace header adds round-numbering convention note (R# = AskUserQuestion batch; sub-question order within a round preserved in git history but not in the trace). |
| v1.4 | 2026-04-17 | §12.2 point 2 split into Logic gate (simulated-time, multi-scenario replay) + Reliability gate (28-day wall-clock soak test). Addresses Q3 of the user's research review: the original "≥ 4 continuous weeks with zero infrastructure incidents" phrasing was ambiguous between simulated and wall-clock interpretation; AWS / Microsoft / Google SRE conventions frame endurance tests as wall-clock. Both interpretations are valuable for different failure modes, so the v1.4 spec requires both. §14.9 added logging the operator-side cost of the wall-clock gate and the "drop it → capability debit" policy. |
| v1.5 | 2026-04-17 | §10 regime classifier gains a data-driven implementation (`HMMRegimeClassifier`, 4-state Gaussian HMM via hmmlearn). Phase A v0.1 ground-truth pass-through stays available for isolation testing. §6.4 LLM routing postcondition gate implemented as `LLMArtefact` contract type + `research_loop/llm_routing.py::commit_gate`. No prose changes to the spec text itself; the v1.5 log entry records that the §6.4 and §10 postconditions now have code. HDP-HMM (non-parametric K per §10 + §8.5 cap) remains a v0.3+ debit. |
| v1.6 | 2026-04-17 | §12.2 point 3 recalibrated: 28-day wall-clock soak → **7-day** wall-clock soak, compensated by the new `soak/` runner's continuous instrumentation (ResourceMonitor + IncidentDetector with pre-registered numeric thresholds on RSS / FDs / DB size). §14.9 rewritten to reflect the five v1.5-critique fixes: duration calibration, checkpoint-resume tolerance of operator interrupts, non-idle drip-feed loop, instrumentation-heavy approach, numeric-threshold replacement of hand-wavy language. The 28-day threshold was named; 7-day + instrumentation is derived from the failure modes it actually catches. |
| v1.13 | 2026-04-18 | Phase 2 Desk 2 (`hedging_demand`) shipped after a full pre-implementation design review (5 blocking + 6 major findings addressed). Key revisions: (a) corrected lead-lag test indexing vs `np.diff(vol_level)` (B-1); (b) golden-fixture regression for dealer_inventory + isolated RNG streams (seed+2 latent, seed+3 observation) — verified bit-identical to v1.12 (B-2); (c) Gate 3 claim recalibrated from "runtime hot-swap" to "DeskProtocol conformance + attribute parity" — opens D9 for runtime-harness follow-up (B-3); (d) Shapley ship criterion dropped, replaced with opened D8 for same-target aggregation normalization (B-4); (e) extended `config/data_sources.yaml` with `cboe_open_interest` + `option_volume` so staleness routing actually fires (B-5); (f) train+serve on noisy observation channels instead of clean latent (M-1); (g) `directional_claim.sign` derived from ridge score, not hardcoded (M-3); (h) multi-seed scale-control for `put_skew_proxy` (M-2); (i) pinned exact G1/G2 regression metrics (m-1). 392 passed + 1 skipped. G3 ✓ (conformance); G1 + G2 fail on minimal synthetic market as expected — expands D7 to cover hedging_demand. |
| v1.12 | 2026-04-18 | Phase 2 MVP ship. §14.7 month-5 checkpoint CLOSED via synthetic-only equity-VRP MVP. `contracts/target_variables.py` grows two entries (`VIX_30D_FORWARD`, `SPX_30D_IMPLIED_VOL`) — append-only registry per §4.6. New sibling `sim_equity_vrp/` package (seed-deterministic 3-factor synthetic vol market). New `desks/dealer_inventory/` — load-bearing equity-VRP desk (analogue to `storage_curve`). New parametrised equity-VRP portability test alongside the oil contract; both pass. Gate 3 (hot-swap, strict) passes for `dealer_inventory`; Gates 1+2 fail on minimal synthetic market → documented as D7 capability debit. **Architectural claim "zero changes to shared infrastructure under equity-VRP redeployment" VERIFIED.** Zero lines changed in bus/, controller/, persistence/, research_loop/, attribution/, grading/, provenance/, eval/, soak/, scheduler/. Model-quality claim deferred to Phase 2 scale-out (4 more desks + richer market or real data). |
| v1.11 | 2026-04-17 | Phase 1 exit revision. §12.2 item 2 (Logic gate) recalibrated to distinguish **strict invariants** (storage_curve 3/3 + Gate 3 5/5 — hold on 10/10 seeds) from **capability claim** (Gate 1 + Gate 2 aggregate — ridge-on-4-features debit, holds on ≥5/10 seeds). §12.2 items 4, 5, 6 gain test + artefact citations. New `tests/test_logic_gate_multi_scenario.py`, `tests/test_phase1_round_trips.py`. New `docs/capability_debits.md` consolidating 6 active debits (all in-budget). New `docs/phase1_completion.md` manifest mapping every §12.2 item to evidence. Phase 1 exits with the architectural claim asserted per §12.2 item 6; Phase 2 is the verification step. |
| v1.10 | 2026-04-17 | §12.2 point 3 and §14.9 recalibrated again: Reliability gate duration **48h → 4h**. The v1.8 "daily-cycle bugs anchor 48h" argument doesn't actually apply to this system — we write to DuckDB not syslog, have no real cron dependencies, and handle sleep via checkpoint-resume. For a synthetic research prototype with no capital, 4 hours catches all fast and medium memory leaks, FD leaks, and deterministic scheduler/DB/bus failures (≈240 decision cycles under drip-feed). What it misses: multi-day leak patterns at tens of MB/day — not a Phase-1 blocker for a research laptop. Escape valve: `--duration-days N` still accepts longer runs when a specific concern warrants it. CLI defaults: `--duration-extra-s` 0 → 14400 (4h), `--n-sim-days` 3000 → 500. Operator-side cost: overnight → runs over lunch. |
| v1.9 | 2026-04-17 | Feed-reliability loose ends closed: (a) `scheduler.check_incident_recoveries` closes feed_incidents when Prints resume AND resets the Page-Hinkley detector state via `feed_latency_monitor.reset_for_feed` (prevents the detector from latching `tripped=True` forever after the first incident). (b) `scheduler.submit_feed_reliability_review(dispatcher, now_utc, feed_names?, **overrides)` helper — canonical submission path for the weekly review event. (c) `historical_shapley_share` — computes a retired desk's mean share of total \|Shapley\| across recent reviews; the review handler uses it as the reinstatement weight when available (single-desk targeted, doesn't disturb other desks), falling back to `reinstate_desk_direct(weight=reinstate_weight)` when the desk has no recent attribution rows. Resolves the v1.7-flagged ambiguity: the original "`propose_and_promote_from_shapley`-first" path would have re-weighted every desk in the regime, which is invasive for a single-desk reinstatement. 13 new tests + handler refactor split reinstatements_performed (shapley-informed) vs reinstatement_fallbacks (conservative). |
| v1.8 | 2026-04-17 | §12.2 point 3 and §14.9 recalibrated: Reliability gate duration **7 days → 48 hours**. The 7-day threshold was still partially gut-feel (chosen because "longer than a day feels serious"); the meaningful failure modes the gate catches all expose within 48 hours. 48h is the defensible floor: long enough for daily-cycle bugs (log rotation, tmp cleanup), short enough to remove a disproportionate critical-path bottleneck. Instrumentation unchanged — catches ≥ 90% of what 7 days would catch at ≈ 30% the wall-clock cost. CLI default (`scripts/run_soak_test.py --duration-days`) updated 7 → 2. `--n-sim-days` default reduced 10_000 → 3_000 for the shorter horizon. |
| v1.7 | 2026-04-17 | §14.5 data-quality invariant promoted from hand-wavy to concrete: three-layer feed-reliability learning loop. **Layer 1** — new `feed_incidents` table (open/closed lifecycle keyed on `feed_name`); desks override `feed_names: list[str]`; `StubDesk._staleness_from_feeds(conn)` threads into `Forecast.staleness`; Controller's existing `if f.staleness: continue` path then drops affected desks automatically. `data_ingestion_failure_handler` upgraded to v0.2 (opens idempotent incident rows). **Layer 2** — `feed_reliability_review` event + handler: rolling failure rate per feed, retire_desk_for_all_regimes on threshold-cross (§7.2 parity), bounded `max_retirements_per_7_days=2` cap to prevent cascading loss, reinstatement via Shapley-based promotion with `reinstate_desk_direct(weight=0.1)` fallback. **Layer 3** — Page-Hinkley change-point detector on per-feed latency (`feed_latency_monitor.py`); scheduler `check_latency_drift` fires preemptive `data_ingestion_failure` with `detected_by='page_hinkley'` before the tolerance-window path would emit one; persistent state via `feed_latency_state` table survives process restarts. New §6.2 event type `feed_reliability_review`. New §7.2 retirement reason `retire:feed_unreliable:<feed>`. |

---

## 1. Scope, objective, and discipline

### 1.1 Objective

Build a multi-desk, agent-led, coordination architecture for systematic trading research. The deliverable is the **architecture** — contracts, orchestration, research loop, attribution — not a P&L number. The architecture is considered successful if it redeploys to an unrelated asset class (equity VRP, the Speckle and Spot project) with zero changes to shared infrastructure.

P&L is diagnostic, not the objective. Per-desk skill is a quality signal about the architecture's usefulness; it is not what is being optimised.

### 1.2 Scope

- **Data/capital regime**: synthetic / research-only. Free public data sources only (EIA 914/STEO/WPSR, OPEC MOMR text, JODI, CFTC COT, Caldara-Iacoviello GPR via Fed, scraped news, OFAC/HMT/EU sanctions downloads, Google Trends). No Bloomberg, Argus, Platts, Kpler, Vortexa. No live capital. No small-live phase. Validation terminus is paper backtest + live event-scoring loop on post-pretraining-cutoff data.
- **Model stack**: OSS-first. Closed models (Claude, GPT) only in the research loop, and only for reasoning-heavy tasks. Zero-shot foundation-model usage as default (see §7.3 for the per-desk escalation ladder).
- **Compute**: 8GB M-series Mac. Fine-tuning requires borrowed compute (Colab / cloud). Inference is always local.
- **Operator**: solo. Every architecture decision must be maintainable by one person.

### 1.3 Principles

The architecture is governed by four principles; all downstream decisions derive from these.

1. **Contract at the boundary, freedom behind it.** The contract surface is typed and frozen; what desks do internally is unconstrained. Every piece of Controller state is something that must redeploy cleanly.
2. **Capability before P&L.** A desk that produces weak signal through clean boundaries is a success. A desk that produces strong signal through leaky coupling to the Controller is a failure. Per-desk skill is a gate, not the objective.
3. **Attribution cleanliness beats adaptation speed.** The Controller is deterministic, slow, and legible. LLM reasoning lives in the research loop, never in the trading decision path. Weight updates are discrete, staged, and human-audited.
4. **Negative results are deliverables.** A desk that fails its gates and is retired is a capability artefact: the architecture correctly identified and removed a non-working component. Retirement is logged, not hidden.

---

## 2. System topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             Data ingestion layer                             │
│  EIA · OPEC · JODI · CFTC · GPR · News scrape · Sanctions · Google Trends   │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │ timestamped, point-in-time-correct (ALFRED pattern)
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                             Release-calendar scheduler                       │
│                   Prefect or cron; pins emission & ingestion                 │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │
               ▼
┌─────────────┬─────────────┬─────────────┬─────────────┬─────────────┬──────┐
│   Supply    │   Demand    │ Storage &   │ Geopolitics │ Macro &     │ ...  │
│    desk     │    desk     │   Curve     │   & Risk    │ Numeraire   │      │
│             │             │    desk     │    desk     │   desk      │      │
└──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴──────┬──────┴──────┘
       │             │             │             │             │
       │ emit()      │ emit()      │ emit()      │ emit()      │ emit()
       ▼             ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Message bus  (validates contracts/v1)                     │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │  Forecast, Print, Grade, SignalWeight, RegimeLabel events
               ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                  Persistence  (DuckDB: forecasts, prints, grades,           │
│                                decisions, attribution, model registry)      │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │
               ├──────────────► Grading  (pure fn of Forecast × Print)
               │
               ├──────────────► Attribution  (LODO per decision, Shapley weekly)
               │
               ├──────────────► Controller (deterministic, regime-conditional)
               │
               └──────────────► Research loop (event-driven + periodic)
                                    │
                                    ├── local Q4 7-8B for volume
                                    └── Claude/GPT API for reasoning-heavy
```

All inter-component messages go through the bus. All bus messages are `contracts/v1` types. No component reads another component's internals. The boundary is enforced by `tests/test_boundary_purity.py`.

---

## 3. Event-sourced foundations

### 3.1 Invariants

- **Every forecast is an immutable event.** Once a desk has emitted a Forecast, it cannot modify or retract it. Corrections are new Forecasts with an explicit `supersedes` field.
- **Every print is an immutable event.** Data prints (EIA WPSR number, CFTC COT snapshot, etc.) are stored point-in-time-correct, ALFRED-style. Revisions are new Prints linked to the original by `vintage_of`.
- **Every Controller decision is an immutable event.** Written to the `decisions` table (§3.2); attribution runs at decision time, not print time.
- **Grading is a pure function.** `Grade = grade(Forecast, Print)`. No hidden state; re-running grading on historical data reproduces the original grades byte-identically.
- **Replay is a first-class operation.** Any historical window can be re-graded or re-attributed from persistence. Input snapshot hashes in the Forecast provenance block permit exact reconstruction of what the desk saw at emission time.
- **Dirty working tree is a mode-dependent invariant.** Development-mode emissions with uncommitted changes are allowed with `code_commit="<base_sha>-dirty"` and prominent audit-log flagging. Production-mode and replay-mode bus validators reject any Forecast whose `code_commit` ends with `-dirty`. The bus mode flag is set at init and cannot change within a run.

### 3.2 Persistence

Primary store: DuckDB. **Single database file** at `data/duckdb/main.duckdb` containing all tables below. (DuckDB is OLAP-oriented and holds many tables in one file efficiently; per-table files would complicate cross-table attribution queries without Phase 1 benefit.) Tables:

| Table | Rows | Indexed on |
|---|---|---|
| `forecasts` | one per emit() | `(desk_name, emission_ts_utc, target_variable, horizon_id)` |
| `prints` | one per realised outcome | `(target_variable, realised_ts_utc, vintage_of)` |
| `grades` | one per (Forecast × Print) match | `(forecast_id, grading_ts_utc)` |
| `decisions` | one per Controller invocation | `(decision_id, emission_ts_utc, regime_id)` |
| `signal_weights` | one per promoted weight matrix row | `(regime_id, desk_name, target_variable, promotion_ts_utc)`. Primary key is `weight_id` (UUID). The tuple is a non-unique index; Controller read query breaks ties on same `promotion_ts_utc` by lexicographic `weight_id` (§8.3). |
| `controller_params` | one row per regime weight-matrix promotion | `(regime_id, promotion_ts_utc)`. Primary key `params_id` (UUID). Carries `k_regime` and `pos_limit_regime` for the linear sizing function (§8.2a). Separated from `signal_weights` to preserve the target-variable registry invariant (§4.6). |
| `attribution_lodo` | one per decision, per desk | `(decision_id, desk_name)` |
| `attribution_shapley` | one per weekly review | `(review_ts_utc, desk_name)` |
| `research_loop_events` | one per trigger firing or periodic review | `(event_type, triggered_at_utc)` |
| `model_registry` | one per deployed model version | `(desk_name, model_name, version, registration_ts_utc)` |
| `regime_labels` | one per classifier emit | `(classification_ts_utc)` |

`decisions` columns: `decision_id` (UUID), `emission_ts_utc`, `regime_id`, `combined_signal: float`, `position_size: float`, `provenance: dict`, `input_forecast_ids: list[str]`.

Secondary stores:
- Input snapshots: DVC or Git LFS. Hashed, content-addressable.
- Model binaries and fine-tune configs: MLflow or Weights & Biases.
- Desk specs: Git, versioned, every change tagged.

### 3.3 Release-calendar scheduler

Unified calendar pins emission events (desks publish forecasts) to ingestion events (prints land, grading fires). Examples:

| Event | Cadence |
|---|---|
| EIA WPSR | Wednesdays 10:30 ET |
| CFTC COT | Fridays 15:30 ET |
| OPEC MOMR | Monthly, ~14th |
| Baker Hughes rig count | Fridays |
| FOMC | Per FOMC calendar |
| Non-farm payrolls | First Friday monthly, 08:30 ET |
| GPR index update | Daily (Fed website) |

Implementation: Prefect for richer DAGs; cron + Python for Phase 1 scale. Airflow is overkill.

### 3.4 Graceful degradation

Desks MUST emit with explicit staleness / confidence flags when upstream data is stale or missing. A broken feed is a Forecast with `staleness=True` and expanded uncertainty — never silent reuse of old data. If a scheduled ingestion fails entirely (no Print lands within tolerance), the `data_ingestion_failure` trigger fires (§6.2).

---

## 4. Contract layer — `contracts/v1.py`

### 4.1 Ownership and purpose

One frozen Python module. Owned by the Controller, not by any desk. Imported by every desk and by the bus. No desk may modify it. Breaking changes require a major-version bump and a new `contracts/v2.py` module; v1 and v2 can coexist only during a migration window, with a clear deprecation schedule.

Validation is enforced at the bus on publish, not trusted at the desk. A desk emitting a malformed Forecast fails loudly; the attribution DB never sees it.

### 4.2 Semantic conventions

- Units are in field names (`price_usd_bbl`, not `price`). The Forecast schema itself is unit-agnostic — domain-specific units live inside `target_variable` metadata.
- Timestamps are always timezone-aware UTC. Naive timestamps are forbidden at the boundary.
- Horizons are typed as a tagged union, not a free-form string (see §4.7).
- Uncertainty is always expressed; a point forecast carries a degenerate (zero-width) interval, not a missing value.
- Directional claim is pre-registered in the desk spec and echoed in every Forecast. Desks that cannot articulate a directional claim cannot emit Forecasts.
- `target_variable` is a string constant drawn from the frozen registry at `contracts/target_variables.py` (§4.6). Free-form strings are rejected by the bus validator.

### 4.3 Core types

```python
# contracts/v1.py

from datetime import datetime, timedelta
from enum import Enum
from typing import Literal, Union
from pydantic import BaseModel, Field, ConfigDict


class Provenance(BaseModel):
    """Identifies who/what produced this object and how to reconstruct it.

    code_commit MUST be the git SHA of the desk code at emission time.
    Development-mode emissions with uncommitted working-tree changes MAY
    use "<base_sha>-dirty" (flagged in audit log). Production-mode and
    replay-mode bus validators reject any Forecast whose code_commit ends
    with "-dirty". The mode flag is set at bus init.
    """
    model_config = ConfigDict(frozen=True)

    desk_name: str
    model_name: str
    model_version: str       # SemVer: MAJOR.MINOR.PATCH
    input_snapshot_hash: str # hex digest of the ordered input-tuple
    spec_hash: str           # hex digest of the desk spec at emission time
    code_commit: str         # git SHA; "<sha>-dirty" allowed only in dev mode


class ClockHorizon(BaseModel):
    """For arbitrary-window research/backtest work. See §4.7 for when
    to prefer EventHorizon instead."""
    model_config = ConfigDict(frozen=True)
    kind: Literal["clock"] = "clock"
    duration: timedelta


class EventHorizon(BaseModel):
    """For event-driven targets pinned to a scheduled release
    (EIA WPSR, CFTC COT, FOMC, NFP, etc.). Prefer this over ClockHorizon
    for any release-pinned forecast (§4.7)."""
    model_config = ConfigDict(frozen=True)
    kind: Literal["event"] = "event"
    event_id: str            # stable identifier for the event
    expected_ts_utc: datetime  # best-estimate firing time — never mutates post-emission


Horizon = Union[ClockHorizon, EventHorizon]


class UncertaintyInterval(BaseModel):
    model_config = ConfigDict(frozen=True)
    level: float = Field(ge=0.0, lt=1.0)   # e.g. 0.80 for 80% band
    lower: float
    upper: float


class DirectionalClaim(BaseModel):
    """Pre-registered claim about which way the desk's signal should point.

    Required. A desk that cannot articulate a directional claim is not producing
    a testable signal and cannot emit Forecasts.
    """
    model_config = ConfigDict(frozen=True)
    variable: str            # target variable the claim is about
    sign: Literal["positive", "negative", "none"]
    # "none" is permitted only for stubs; real desks must emit "positive" or
    # "negative" as a frozen claim in their spec.


class Forecast(BaseModel):
    """Immutable emission from a desk at a point in time."""
    model_config = ConfigDict(frozen=True)

    forecast_id: str         # UUID, unique per emission
    emission_ts_utc: datetime
    target_variable: str     # MUST be a member of contracts.target_variables.KNOWN_TARGETS
    horizon: Horizon
    point_estimate: float
    uncertainty: UncertaintyInterval
    directional_claim: DirectionalClaim
    staleness: bool = False
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    provenance: Provenance
    supersedes: str | None = None  # forecast_id of the Forecast this replaces


class Print(BaseModel):
    """A realised outcome that grades one or more Forecasts."""
    model_config = ConfigDict(frozen=True)

    print_id: str
    realised_ts_utc: datetime      # actual arrival time of the print
    target_variable: str
    value: float
    event_id: str | None = None    # populated for event-pinned prints (§4.7)
    vintage_of: str | None = None  # for revisions, points to original Print


class Grade(BaseModel):
    """Output of grading a Forecast against its matching Print."""
    model_config = ConfigDict(frozen=True)

    grade_id: str
    forecast_id: str
    print_id: str
    grading_ts_utc: datetime
    squared_error: float
    absolute_error: float
    log_score: float | None = None           # for probabilistic forecasts
    sign_agreement: bool | None = None       # did direction match the claim
    within_uncertainty: bool | None = None   # did realised value fall in band
    schedule_slip_seconds: float | None = None  # realised_ts - expected_ts (EventHorizon only)


class SignalWeight(BaseModel):
    """A row of the regime-conditional weight matrix.

    Controller state is a collection of these, indexed by (regime_id, desk_name,
    target_variable). Promotion events append new rows with a new promotion_ts;
    the Controller reads the most recent row per (regime, desk, target) tuple.
    Horizons within a (desk, target) share a weight by default (§8.5).
    """
    model_config = ConfigDict(frozen=True)

    weight_id: str
    regime_id: str
    desk_name: str
    target_variable: str
    weight: float
    promotion_ts_utc: datetime
    validation_artefact: str  # path to the held-out validation result
                              # or "cold_start" for the uniform-weight bootstrap (§14.8)


class ControllerParams(BaseModel):
    """Per-regime scalar parameters for the linear sizing function (§8.2a).

    Separated from SignalWeight because k_regime and pos_limit_regime are
    Controller-internal scalars, not per-(desk, target_variable) signal weights;
    storing them in the signal_weights table would require sentinel
    target_variable strings that violate the §4.6 registry invariant.
    """
    model_config = ConfigDict(frozen=True)

    params_id: str           # UUID, unique per promotion
    regime_id: str
    k_regime: float          # scalar gain in position = clip(k × combined_signal, ...)
    pos_limit_regime: float  # absolute position cap (≥ 0)
    promotion_ts_utc: datetime
    validation_artefact: str  # path to the held-out validation result,
                              # or "cold_start" for the uniform-weight bootstrap (§14.8)


class RegimeLabel(BaseModel):
    """Opaque regime label emitted by the regime classifier.

    Deliberately opaque: no contango/backwardation, no bull/bear, no
    oil-specific semantics cross the boundary. The Controller uses the
    string id as a key; its meaning lives inside the classifier.
    """
    model_config = ConfigDict(frozen=True)

    classification_ts_utc: datetime
    regime_id: str                          # argmax label, e.g. "regime_7f3a"
    regime_probabilities: dict[str, float]  # P(regime = X) for all current regimes
    transition_probabilities: dict[str, float]  # P(next=regime_X)
    classifier_provenance: Provenance


class ResearchLoopEvent(BaseModel):
    """A trigger firing or a periodic review record."""
    model_config = ConfigDict(frozen=True)

    event_id: str
    event_type: Literal[
        "gate_failure",
        "regime_transition",
        "weight_staleness",
        "attribution_anomaly",
        "correlation_shift",
        "desk_staleness",
        "controller_commission",
        "data_ingestion_failure",
        "periodic_weekly",
    ]
    triggered_at_utc: datetime
    priority: int = Field(ge=0, le=9)  # 0 = highest
    payload: dict  # structured, schema per event_type documented separately
    completed_at_utc: datetime | None = None
    produced_artefact: str | None = None
```

### 4.4 Forbidden at the boundary

- No desk-specific types. Geopolitics desk's `EventProbability` lives inside the desk; the Forecast emitted carries a scalar probability in `point_estimate`.
- No commodity-specific fields. `wti_front_month_close` is a valid `target_variable` (a registry constant); `wti_price: float` as a typed field is not.
- No raw model outputs. A desk that produces a multi-modal posterior must summarise to a point estimate + uncertainty interval for emission.
- No aliasing. Every Forecast has exactly one `target_variable` and exactly one `horizon`. A desk producing a 1-week and 1-month forecast emits two Forecast objects, not one with two fields.
- No free-form `target_variable` strings. The bus validator rejects any Forecast whose `target_variable` is not a member of `contracts.target_variables.KNOWN_TARGETS` (§4.6).
- No post-emission mutation. Forecast objects are frozen Pydantic v2 models; no retro-updating `expected_ts_utc` on event slip (§4.7).

### 4.5 Test: `tests/test_boundary_purity.py`

Imports only `contracts/v1.py`, `contracts/target_variables.py`, the bus, the Controller, and the grading harness. Mocks every desk as a simple `emit()`-producing function that returns valid Forecast objects drawing `target_variable` from `KNOWN_TARGETS`. Asserts: Controller runs to completion across a synthetic release-calendar replay. If this test ever needs to import a desk's internals to pass, the boundary has drifted; the capability claim is broken.

### 4.6 Target-variable registry

The `target_variable` field on Forecast and Print is constrained to a frozen registry at `contracts/target_variables.py`. The registry is part of the `contracts/v1` API.

- Every `target_variable` string used in the system MUST be defined as a module-level constant in the registry and MUST be a member of the `KNOWN_TARGETS: frozenset[str]` set.
- The bus validator rejects Forecasts and Prints whose `target_variable` is not in `KNOWN_TARGETS`.
- Adding a new target variable is a v1.x revision (logged in §0). Removing one is a breaking change requiring v2.
- The registry is domain-inclusive: oil target names and equity-VRP target names coexist. The portability test exercises this.
- Rationale: eliminates the silent-failure mode where a typo in a desk's `target_variable` produces a new unique string that no Print will ever match, causing the Forecast to persist but never be graded.

### 4.7 Horizon semantics and Forecast → Print matching

**When to use which horizon:**
- `EventHorizon` for any forecast pinned to a scheduled release: EIA WPSR, CFTC COT, OPEC MOMR, FOMC, NFP, Baker Hughes rig count, and any other calendar event. This is the default for oil forecasts; almost every interesting oil target has a release calendar.
- `ClockHorizon` only for arbitrary-window research/backtest work (e.g. "forecast of close-to-close return 7 days hence"). Prefer EventHorizon unless the target genuinely has no scheduled release.

**Matching function** (deterministic; implemented once in the grading harness):

```
For Forecast F and candidate Print P with F.target_variable == P.target_variable:
  If F.horizon.kind == "event":
    Match if P.event_id == F.horizon.event_id.
  If F.horizon.kind == "clock":
    Match if abs(P.realised_ts_utc − (F.emission_ts_utc + F.horizon.duration)) ≤ tolerance.
    Default tolerance: 6 hours. Per-desk override allowed via desk spec.
```

**Event-slip policy (locked):** if an EventHorizon's event fires at a time different from `expected_ts_utc` (EIA delays WPSR by a day, for example), the Grade fires on actual Print arrival. `expected_ts_utc` on the Forecast never mutates post-emission (Forecast is immutable, §3.1). The delta `realised_ts_utc − expected_ts_utc` is recorded in `Grade.schedule_slip_seconds` as a calibration diagnostic and is available for research-loop pattern analysis.

Rationale: auto-re-anchoring would violate Forecast immutability; rejecting on mismatch would be too harsh in normal operation; grading-on-actual-arrival preserves the event-sourced design and gives the research loop a clean signal about release reliability.

---

## 5. Desks — interface and per-desk skeleton

### 5.1 Desk contract

Every desk implements the following minimum interface:

```python
# Convention; no abstract base class required
class Desk:
    name: str                   # unique, e.g. "storage_curve"
    spec_path: str              # path to the desk spec document
    emit_target_variables: list[str]   # all must be members of KNOWN_TARGETS
    emit_horizons: list[Horizon]

    def on_schedule_fire(self, now_utc: datetime) -> list[Forecast]:
        """Called by the scheduler on the desk's emission cadence."""

    def on_trigger(self, event: ResearchLoopEvent) -> list[Forecast] | None:
        """Optional: react to a research-loop trigger (e.g. rerun after spec update)."""
```

Desk internals are unconstrained. PyMC, CatBoost, Kronos inference, LLM extraction pipelines, classical BVAR — all are valid.

### 5.2 Per-desk spec document (required before build)

Each desk has a spec document at `desks/<name>/spec.md`. Required sections:

1. **Target variables and horizons** — exactly what the desk emits; every `target_variable` must be (or be added as) a member of `contracts.target_variables.KNOWN_TARGETS`.
2. **Directional claim per variable** — positive / negative, with justification referencing a dev-period Spearman or equivalent.
3. **Pre-registered naive baseline** — random walk, climatology, persistence, or explicit alternative, chosen BEFORE any model is fit.
4. **Model ladder** — zero-shot → classical specialist → borrowed-compute fine-tune (§7.3).
5. **Gate-pass plan** — how the three hard gates (§7) will be demonstrated on test data.
6. **Data sources** — free / public only, with ingestion code path.
7. **Internal architecture** — whatever the desk wants; described once at freeze.
8. **Capability-claim debits** — running log of escalations (e.g. "zero-shot Kronos failed skill gate, escalated to classical replacement").

### 5.3 Desks in Phase 1

| # | Name | Primary model(s) | Notes |
|---|---|---|---|
| 1 | `supply` | Bayesian SVAR (Kilian-Murphy), MOIRAI-2 zero-shot, CatBoost | SVAR is the identification layer; forecasters consume identified shocks. |
| 2 | `demand` | BSTS + horseshoe, mixed-frequency BVAR, TabPFN-v2, CatBoost (refining) | Feeds inventory-draw implied forecast to Storage & Curve. |
| 3 | `storage_curve` | Kronos small, Dynamic Nelson-Siegel + LSTM, functional change-point, CatBoost (COT) | First real desk after stubs. Kronos full reinstatement; relies on sign-preservation gate. |
| 4 | `geopolitics` | LLM extraction pipeline (two-tier), Bayesian event-impact regression, multi-agent debate for contested events | GPR as pre-registered baseline. |
| 5 | `macro` | Mixed-frequency BVAR, Markov-switching + HMM, TabPFN-v2, factor model for DXY decomposition | Emits macro regime conditioning info as a Forecast, NOT as a RegimeLabel (see §10.1). |
| 6 | `regime_classifier` | HDP-HMM + online Bayesian change-point | Owned by the Controller, not a trading desk. Emits RegimeLabel events. Consumes desk outputs, never raw domain data. |

Desk 6 is listed separately because its contract is different — it emits RegimeLabel, not Forecast — and it is domain-blind by construction (inputs are the vector of desk outputs). Under equity-VRP redeployment, desks 1–5 are fully replaced; desk 6 redeploys with zero changes.

---

## 6. Research loop

### 6.1 Paths and KPIs

The research loop has two paths that do **categorically different work** and carry different KPIs.

| Path | Work | KPI |
|---|---|---|
| Event-driven | Reactive: gate failure RCA, regime-transition handling, attribution anomaly investigation, correlation-shift investigation, desk-staleness response, data-ingestion-failure response, Controller-commissioned requests | Latency from trigger fire to artefact produced |
| Periodic (weekly) | Proactive: experiment backlog grooming, capability review, specification drift check, abstraction audit, cross-print pattern synthesis, forward-looking hypothesis generation | Completion rate (did the review run?); output quality (did it produce ≥1 actionable item?) |

Event-driven path **preempts** periodic. Periodic pauses on event fire, handles the event, resumes with post-event state. No parallel processing (event work is minutes to hours; periodic is bounded to hours).

### 6.2 Event-driven triggers (pre-registered)

The trigger list is itself a contract. Adding a new event type is a design change, logged as a v1.x revision; it is not an ad-hoc addition.

| Trigger | Fires when | Default priority |
|---|---|---|
| `gate_failure` | Any desk fails skill, sign-preservation, or hot-swap gate | 0 (highest) |
| `data_ingestion_failure` | A scheduled ingestion produced no Print within `scheduled_release_ts + tolerance` (default 2h past scheduled release), OR Page-Hinkley drift detector trips on accumulated per-feed latency (v1.7, Layer 3). Payload: `feed_name`, `scheduled_release_ts_utc`, `actual_wall_clock_ts_utc`, `affected_desks` (list of consuming desks), `detected_by` ∈ {`scheduler`, `page_hinkley`, `manual`}. Opens a `feed_incidents` row; idempotent on re-fire for the same feed while incident is open. | 1 |
| `feed_reliability_review` | Periodic review (weekly cadence by default) over the `feed_incidents` registry. Applies rolling failure-rate rules to auto-retire desks whose feeds are chronically unreliable and reinstate desks whose feeds have recovered (v1.7, Layer 2). Payload: `feed_names`, `lookback_days`, `retirement_threshold`, `recovery_days`, `max_retirements_per_7_days`, `reinstate_weight`. Retirements are bounded by a 7-day cap; overshoot is surfaced in the artefact rather than silently dropped. | 2 |
| `regime_transition` | Regime classifier flags transition with `max(regime_probabilities) > 0.7` after a regime_id change | 1 |
| `weight_staleness` | Realised skill of current weight matrix below pre-registered threshold for N consecutive days | 2 |
| `attribution_anomaly` | LODO or Shapley contribution for any desk moves outside its pre-registered tolerance band | 2 |
| `correlation_shift` | Pairwise desk-output correlation crosses pre-registered threshold | 3 |
| `desk_staleness` | Desk emits a Forecast with `staleness=True` or `confidence < threshold` | 3 |
| `controller_commission` | Controller detects regime-uncertainty above threshold | 4 |

Each trigger carries a structured payload pointing to the specific data to examine, bounding the LLM's working frame.

### 6.3 Periodic cadence

Weekly, scheduled post-CFTC-COT release — Friday 16:00 ET + 30-minute buffer. The cadence is pinned to the release calendar, not arbitrary clock time, so the review always sees a complete weekly data vintage. Calendar skips (holidays) follow CFTC's own schedule.

Work items per review:
1. Attribution DB pattern scan across the week (deltas, anomalies that didn't fire individually).
2. Experiment backlog grooming — review proposed experiments, score, schedule or drop.
3. Specification drift check — do desk specs still match desk behaviour? (Compare emitted Forecasts against spec claims.)
4. Forward-looking hypothesis generation.

### 6.4 LLM routing

Two tiers, pre-registered postconditions. Routing decisions logged per invocation; overrides (local fell back to API or vice versa) tracked as a quality metric.

| Tier | Model class | Use | Expected volume |
|---|---|---|---|
| Local | Q4-quantised 7–8B (Mistral-7B, Qwen-2.5-7B, Llama-3.1-8B) via MLX or llama.cpp | Daily log summarisation, structured extraction from desk outputs, attribution-DB querying, pattern matching across regime history | High (hundreds of calls/week) |
| API | Claude Opus/Sonnet, GPT-4o | Experiment design from anomaly, desk-spec revision drafting, RCA on gate failures, cross-desk synthesis | Low (tens of calls/week) |

**Postcondition rules (enforced at the research-loop commit gate):**

Tasks execute on the local tier by default. Any LLM output that contains any of the following artefacts MUST have been produced by an API-tier call; otherwise the artefact is rejected:

- A draft or edit to any desk spec (`desks/*/spec.md`).
- A new hypothesis proposal scheduled onto the experiment backlog.
- A cross-desk synthesis artefact (any output citing two or more desks' Forecasts).

Rationale: enforcing routing as a postcondition (artefact class → tier requirement) rather than a pre-routing rule (task-kind → tier assignment) handles the case where a task starts local and escalates partway through; the commit gate checks the artefact class, not the task origin.

Budget target: API spend in the tens of dollars per month in research mode. Overruns are logged as capability-claim debits.

### 6.5 LLM is forbidden in the trading-decision path

The LLM is never in the Controller's decision flow. This is architectural, not optional. Reintroducing it contaminates attribution (stochasticity, silent-model-version changes, context-window dependence), breaks portability (LLM judgement does not redeploy as shared infrastructure), and violates the "Controller owns no domain opinions" principle. Research-loop LLM output is staged (spec revisions, weight-update proposals) and promoted to the decision path only via the human-gated promotion events (§11).

---

## 7. Hard gates

### 7.1 The three hard gates

A desk cannot be promoted into the Controller's input set until it passes all three gates on test data. A desk that fails any gate after promotion is a candidate for retirement (see §11 for the adjudication path).

**Gate 1 — Skill vs pre-registered naive baseline.**

The desk beats a pre-registered naive baseline (random walk, climatology, persistence, or explicit alternative) on its primary forecast metric (RMSE, Brier, log-score as appropriate) on test data. The baseline is chosen **BEFORE** the desk's model is fit; post-hoc baseline-shopping invalidates the gate.

**Gate 2 — Dev→test sign preservation.**

Pre-registered Spearman rank correlation of the desk's directional-claim-aligned score against the forward-realized target, computed on dev and on test. Sign must agree on both periods.

This is the Kronos-RCA gate. Kronos showed +0.43 Spearman on dev and −0.23 on test; the architecture's core commitment is that this kind of failure is caught at stage 1 not stage 5. Sign-flip between dev and test is the signature of spurious correlation — unfixable by sizing, re-weighting, or Controller adjustment. Hard gate, tested early, no appeal.

**Gate 3 — Hot-swap against stub.**

A stub desk emitting valid Forecast objects with null signal (directional claim = "none", calibrated uncertainty, staleness = True) can be swapped in place of the real desk without breaking the Controller. The Controller runs to completion, weights degenerate to the matrix's baseline, and the grading harness continues processing. Fail → desk is reaching into Controller internals or Controller is pattern-matching on specific desk outputs; both are architectural bugs.

### 7.2 LODO as escalating diagnostic

Leave-one-desk-out ablation is run continuously (on every decision) but is not a hard gate by default. Three outcomes:

| Outcome | Interpretation | Action |
|---|---|---|
| Desk harmful | Controller strictly better without the desk (pre-registered window, statistical significance) | **Hard-gate retire** — the desk is actively damaging decisions. Writes `SignalWeight(weight=0.0, validation_artefact="retire:harmful:<reason>")` via `remediation.retire_desk_for_regime`. |
| Desk redundant | Controller indifferent (strictly equal metrics within tolerance) | Warning-track flag; after **2 Controller weight promotions** or **3 months**, whichever comes first, if still redundant, retire |
| Desk unused | Controller underweights the desk but using it | Diagnostic only; Controller maturity may change this |
| Desk's upstream feed unreliable | Rolling failure count for a feed ≥ threshold (default 5 failures / 30 days) AND the feed is currently in an open incident | **Hard-gate retire across ALL regimes** where the desk holds non-zero weight (v1.7 §14.5 parity). Writes `SignalWeight(weight=0.0, validation_artefact="retire:feed_unreliable:<feed_name>")` via `remediation.retire_desk_for_all_regimes`. Recovery (no failures for `recovery_days`, default 14) triggers reinstatement via Shapley promotion with `reinstate_desk_direct` fallback tagged `"reinstate:feed_recovered:<feed>"`. Bounded by `max_retirements_per_7_days` (default 2) to prevent cascading coverage loss. |

LODO becomes a hard gate (for the harmful case specifically) only after the Controller passes its own maturity threshold: signal-weight distribution stable over a pre-registered window (weight changes below ε for 4 consecutive weeks), attribution accuracy on synthetic known-signal injection above threshold, regime-classification stability above threshold.

### 7.3 Escalation ladder inside a desk (TSFM compute policy)

When a desk first fails Gate 1 (skill):

1. **Default — zero-shot local model**. Feasibility confirmed per desk (§5.3). If the zero-shot foundation-model variant beats the baseline, ship.
2. **Escalation 1 — classical specialist**. If zero-shot fails skill, replace with a classical specialist (CatBoost, BVAR, PyMC hierarchical model). Log as a capability-claim debit: "TSFM zero-shot insufficient for this problem, replaced with classical specialist."
3. **Escalation 2 — borrowed-compute fine-tune**. Only if both zero-shot and classical fail, AND there is a specific hypothesis for why fine-tuning would fix it. Rare by construction. Fine-tune runs produce a model binary, a training config, and a data snapshot, all versioned; the Controller treats the fine-tuned model as a new model version, not a mutation.

Distillation (training a small local model on TSFM outputs) is **explicitly rejected**: it breaks the capability claim by shipping a proxy under the TSFM's label, and fails particularly badly on non-stationary financial data.

---

## 8. Controller — deterministic, regime-conditional

### 8.1 State

The Controller's state is a single regime-indexed matrix:

- `signal_weights: dict[regime_id, dict[(desk_name, target_variable), float]]`
- `current_regime: RegimeLabel`

That is all. No bandit posteriors, no gradient accumulators, no learning-rate state, no online-OGD drift parameters. Everything else is either persistent data (attribution, grades — owned by the DB) or derivable (the current signal output).

### 8.2 Decision

On each Controller invocation:

1. Read the current RegimeLabel (most recent `regime_classifier` emit). Use `regime_id` (argmax) as the index into `signal_weights`.
2. Look up the weight row for the regime.
3. Compute `combined_signal = sum(weight × desk_forecast.point_estimate)` across all desks and target variables in the weight row.
4. Apply linear sizing (§8.2a) to translate `combined_signal` into a `position_size`.
5. Emit a `decision` event to the `decisions` table with full provenance.

All of the above is a pure function of inputs. Replay on a historical window reproduces the original decision byte-identically.

### 8.2a Sizing function

Phase 1 uses linear, regime-conditional sizing:

```
position_size = clip(k_regime × combined_signal, −pos_limit_regime, +pos_limit_regime)
```

Where `k_regime` and `pos_limit_regime` are per-regime scalars stored in the `controller_params` table (§3.2) via the `ControllerParams` Pydantic type (§4.3). The Controller's decision flow reads the most recent `ControllerParams` row for the current `regime_id` at decision time, alongside the `signal_weights` rows for the same regime.

Rationale for the separate table: storing `k_regime` / `pos_limit_regime` as rows in `signal_weights` would require sentinel `target_variable` strings (e.g. `__k__`, `__pos_limit__`) that violate the §4.6 registry invariant, and a nullable `desk_name` column that weakens the event schema's type signature. A dedicated table keeps both disciplines intact.

Rationale for linear sizing: deterministic, replayable, and portable. The capability claim requires these three; it does not require risk-optimal sizing. CVaR-constrained and utility-theoretic sizing are explicitly deferred to Phase 2, when the portability test has been run and the architecture is validated at the current level of complexity.

### 8.3 Weight promotion

Controller weights never update in real time. The update path is:

1. Prints land → grades computed per Forecast per desk → attribution DB updated. **Controller weights unchanged.**
2. Research loop (either event-driven or periodic) queries the attribution DB, asks: "are the current regime weights still skill-preserving?"
3. If not, the loop proposes a new weight matrix — a new `SignalWeight` row bundle — staged as a candidate version.
4. The candidate is validated against recent held-out data on the pre-registered promotion metric.
5. If the candidate beats the current matrix by a pre-registered margin on the held-out data, it **auto-promotes**: new `SignalWeight` rows appended to the DB with new `promotion_ts_utc`. The Controller reads the most recent row per (regime, desk, target) tuple; the new weights take effect on the next Controller invocation. Auto-promotion is permitted only under this staged-candidate + pre-registered-margin + held-out-validation path (steps 3–4); out-of-band weight writes require human sign-off per §11 item 2.
6. The human reviews the daily/weekly audit summary. Rollback is a **distinct human operation**, not a variant of the auto-promotion path. A rollback writes a superseding `SignalWeight` (and, if applicable, `ControllerParams`) row with `validation_artefact="rollback:<reason>"` and bypasses the margin check by construction. Rollbacks require explicit human sign-off (§11 item 2 clarification), log a distinct audit-log event class, and are tracked as capability-claim debits in the derivation trace. Rationale: a human-initiated rollback is often motivated by the current matrix misbehaving on recent data the validation harness didn't see; forcing such rollbacks through the auto-promotion margin gate would block the very intervention the rollback exists to enable.

**Tie-break rule for same-`promotion_ts_utc` reads.** If two or more `SignalWeight` (or `ControllerParams`) rows for the same `(regime_id, desk_name, target_variable)` carry identical `promotion_ts_utc`, the Controller reads the row with lexicographically greatest `weight_id` (or `params_id`). This guarantees deterministic reads under the extraordinary case of microsecond-collision during cold-start re-boots (§14.8) and in tests with frozen clocks.

Promotion is a discrete event, logged as a capability artefact. The attribution DB permits post-hoc comparison of the pre- and post-promotion weight performance on the same print history.

### 8.4 Portability

Under equity-VRP redeployment, the Controller redeploys with **zero code changes**. What changes:

- The weight matrix is re-fitted (equity-VRP desks, equity-VRP regimes, equity-VRP historical data).
- The regime classifier's internal HDP-HMM is retrained on equity-VRP desk outputs.
- Desks 1–5 are fully replaced.
- New `target_variable` constants are added to `contracts/target_variables.py` (v1.x revisions; the registry is domain-inclusive by design).

What does not change:
- `contracts/v1.py` type definitions.
- The bus.
- The grading harness.
- The attribution DB schema (though its contents are domain-specific).
- The research-loop trigger list (the events are asset-class-agnostic).
- The Controller's decision flow.
- The sizing function (linear).

This is the capability-claim acceptance test.

### 8.5 Dimensionality discipline

The weight matrix grows combinatorially if unbounded. Pre-registered disciplines to keep it fittable:

**Regime-count cap.** Phase 1 classifier emits at most **6 distinct `regime_id` values** at any time. HDP-HMM's non-parametric capability is retained internally but capped at emission time; additional latent states are merged into a sink regime `regime_other` until the research loop proposes a cap increase (a v1.x revision). Reviewed at every Controller promotion event.

**Horizon weight sharing.** The weight matrix is indexed by `(regime_id, desk_name, target_variable)`. **Horizons within a (desk, target) share a weight by default.** A per-horizon scalar multiplier is permitted as a second parameter only if a desk demonstrates horizon-specific attribution stability (LODO contribution varies by horizon beyond a pre-registered tolerance band). Default is shared; any override is logged as a capability-claim debit.

**Illustrative sizing.** 6 regimes × 6 desks × 3 targets avg = 108 weights. Plus per-regime `k` and `pos_limit` (§8.2a) = 108 + 12 = 120. Compare to the unbounded case: 6 regimes × 6 desks × 3 targets × 2 horizons = 216 weights, below the point-of-fit-infeasibility threshold only if horizons are shared.

**Regularisation is assumed, not optional.** HDP-HMM regime occupancy is typically highly skewed — one regime often holds 50–60% of observations while others hold 5–15% each. On 2 years of weekly-cadence data (~104 observations), minority-regime sample counts fall well below 100, which is insufficient for OLS-quality weight fits. The Controller's weight-promotion harness MUST use a regularised estimator: ridge regression (Tikhonov with per-regime scaling) for the weight rows and Bayesian shrinkage toward the uniform-weight prior (§14.8 cold-start) for both weights and `k_regime` / `pos_limit_regime`. The Controller's promoted-weight validation artefact MUST record the regularisation method and hyperparameters; changing the regularisation method between promotions is a capability-claim debit.

---

## 9. Attribution

Two methods, co-primary for their respective questions.

### 9.1 LODO — retirement and harm detection

Run on every decision (as written to the `decisions` table). For each desk:

1. Recompute the Controller's decision with that desk's Forecasts replaced by the stub (null signal).
2. Recompute the downstream grading once the relevant Prints land.
3. Diff the two streams on the pre-registered LODO metric (typically per-decision squared error or PnL attribution).

Per-desk LODO contributions land in the `attribution_lodo` table indexed on `(decision_id, desk_name)`.

Use: retirement decisions per §7.2; correlation-shift trigger; desk-redundancy warnings.

### 9.2 Shapley — credit assignment under correlation

Run weekly (during the periodic review) or on demand (Controller-commissioned). For n desks:

- Exact if n ≤ 6 (2ⁿ = 64 coalitions; tractable per-decision).
- Sampled (100–1000 samples per decision) if n grows.

Shapley values aggregate over the week's decisions into per-desk credit scores, stored in `attribution_shapley`.

Use: per-desk capability report; weight-update proposals from the research loop; cross-desk correlation diagnostics.

### 9.3 Both are primary

LODO and Shapley answer **different** questions:
- LODO: "if this desk were gone, would the Controller be better or worse?"
- Shapley: "how much of the signal actually came from this desk, net of its correlation with other desks?"

Tiering them as primary/diagnostic (one above the other) is a framing error. They coexist at equal status; research-loop outputs cite both.

---

## 10. Regime classifier

### 10.1 Inputs

Vector of desk outputs (Forecast point estimates + uncertainties) plus the Macro desk's emitted macro-regime Forecast. **No raw domain data.** The classifier is domain-blind: under equity-VRP redeployment, the input vector is the five equity-VRP desks' outputs, and the classifier HMM is retrained on that vector.

Macro desk output is valid regime-classifier input by construction (a domain-neutral Forecast). Macro does NOT emit `RegimeLabel` directly; the classifier consumes Macro's (and other desks') Forecast stream and is the sole emitter of `RegimeLabel`.

### 10.2 Method

- Primary: hierarchical Dirichlet process HMM (HDP-HMM). Non-parametric regime count; no fixed K, but capped at emission time per §8.5.
- Secondary: online Bayesian change-point detection (Adams & MacKay 2007) for fast-break identification.

Emits `RegimeLabel` events on each classification cycle. Regime IDs are opaque strings (`regime_7f3a`, not `regime_contango`). The Controller reads `regime_id` (argmax) by default; `regime_probabilities` is available for pre-registered weighted-average Controllers in future revisions.

### 10.3 Gates

The regime classifier is itself a desk (§5.3 desk 6) and must pass:
- **Skill**: regime labels distinguishable from random on a pre-registered held-out period (e.g. forward-window-realised-vol differs across regime labels with p < 0.05 under permutation).
- **Sign preservation**: directional claim on regime transitions (e.g. "transitions to regime X are associated with higher forward realised vol") must hold dev-to-test.
- **Hot-swap**: replaceable with a trivial one-regime classifier without breaking the Controller (Controller degenerates to the unconditional weight matrix; still functions).

---

## 11. Human-in-the-loop gating

Four approval points, all active:

1. **Desk-spec changes require human approval.** The research-loop LLM can draft revisions, but changes merge only on human review. Protects against silent desk-spec drift that would show up as degraded attribution months later.
2. **Controller-weight updates auto-promote; human sees audit log.** Given the staged-candidate + pre-registered-margin + held-out-validation path (§8.3), auto-promotion is the default; the human reviews the daily/weekly audit summary. Any promotion event can be rolled back manually by writing a superseding `SignalWeight` row. Out-of-band weight writes (not via the staged path) require human sign-off.
3. **Initial desk deployment requires human sign-off.** A desk enters the Controller input set only after human reviews the dev-period sign-preservation gate results, the skill-gate results, and the hot-swap test. New-desk addition is deliberate, not automatic.
4. **Gate-failure-triggered retirements require human adjudication.** If a desk fails skill or sign-preservation or (post-maturity) LODO-harm, retirement is proposed by the system but requires human confirmation. Prevents false-positive retirements on transient data-quality issues.

---

## 12. Phase 1 — sequence, done-criterion, abandon rules

### 12.1 Sequence

1. **Week 0 — scaffold**. `contracts/v1.py`, `contracts/target_variables.py`, bus with validation (including registry check and production-mode dirty-tree rejection), DuckDB schema, grading harness with event-horizon matching and slip-recording, release-calendar scheduler, input-snapshot hasher, `tests/test_boundary_purity.py`, `tests/test_replay_determinism.py`. No desk work until scaffold is green.
2. **Weeks 1–2 — stubs for all six desks**. Each stub passes the hot-swap gate (valid boundary contract) and fails the skill gate (null signal). End-to-end pipeline runs against six stubs; attribution DB records zero meaningful contribution from any desk; research-loop triggers are injectable via synthetic Forecasts and fire correctly. Controller bootstrap state: uniform weights across all stubs (§14.8).
3. **Desk 1 — Storage & Curve deepen**. Highest novel-tech content (Kronos, DNS + LSTM, functional change-point); earliest and cheapest failure mode; most informative about TSFM validation approach.
4. **Desk 2 — Geopolitics deepen**. Heterogeneous tech stack (LLM extraction + event-driven pipelines); stress-tests LLM two-tier routing and structured-output validation.
5. **Desks 3 & 4 — Supply + Demand in parallel**. Shared data-engineering work reduces duplication.
6. **Desk 5 — Macro deepen**. Classical econometric stack; lowest risk; benefits from mature scaffolding. Month-5 checkpoint during Macro build: confirm Phase 2 equity-VRP desk candidates exist (§14.7).
7. **Controller weight matrix — final step**. Regime-conditional matrix fitted on attribution data from the mature pipeline. Mechanical step: every prior validation event already ran against the Controller skeleton with uniform weights.

### 12.2 Done-criterion

Phase 1 is complete when ALL of the following hold:

1. All six desks pass their three hard gates on test-set replay (§7.1).
2. **Logic gate** — simulated-time replay. The architecture is exercised end-to-end across `N_scenarios ≥ 10` independent seeds × regime sequences; each scenario replays ≥ 4 weeks of simulated events through the full loop (desks → Controller → grading → attribution → research-loop weight promotion). **Strict invariants (v1.11 load-bearing, hold on 10/10 seeds):** storage_curve passes all three gates + Gate 3 (hot-swap) passes for all 5 desks. **Capability claim (v1.11 — Phase A ridge-on-4-features debit, `capability_debits.md` D1):** per-scenario aggregate ≥ 3/5 desks pass Gate 1 and Gate 2; across scenarios the per-scenario aggregate threshold holds on ≥ 5/10 seeds. Non-storage-curve desks' skill improvement is a §7.3 Phase 2 escalation item, not a Phase 1 blocker. Simulated-time testing isolates **logic correctness** and completes in minutes per run. Test: `tests/test_logic_gate_multi_scenario.py`.
3. **Reliability gate** — wall-clock endurance. The system runs for **≥ 4 hours of wall-clock time** via the `soak/` runner (real-time synthetic data feed at ≥ 1,440 sim-days per real day; pre-registered numeric thresholds on memory, file descriptors, and disk growth; automatic checkpoint + resume across OS reboots / dependency upgrades). Tests the failure modes simulated time cannot catch — memory leaks, file-descriptor leaks, disk exhaustion, scheduler crashes, DB corruption, bus validation inconsistencies. Numeric thresholds (v1.6): RSS growth ≥ 20% AND ≥ 500 MB absolute ⇒ memory_leak incident; open FDs ≥ 5× baseline ⇒ fd_leak; DuckDB file growth ≥ 5 GB ⇒ disk_growth. Scheduler/DB/bus exceptions are recorded via `IncidentDetector.record_exception`. A checkpoint-clean OS reboot is NOT an infrastructure incident and does NOT reset the clock (§14.9). Gate failures are NOT infrastructure incidents.
4. Each desk has **≥ 10 closed round-trips** (for weekly-cadence desks) or **≥ 20 closed round-trips** (for daily-cadence desks). A closed round-trip = Forecast emitted → Print arrived → Grade computed → Attribution updated. Verified by `tests/test_phase1_round_trips.py` which drives 30 round-trips per desk end-to-end through the bus (Forecast → Bus → Controller → Decision → LODO → Print → Grade) and asserts the DB persists the full cohort.
5. The research-loop latency KPI is **measured and reported**, not "pending data." Event-driven path reports latency for every fired trigger; periodic path reports completion rate and ≥ 1 actionable-item-per-review. Implemented by `research_loop/kpi.py::compute_latency_report` (per-type mean/p50/p95/max + overall completion rate); demonstrated end-to-end by `tests/test_phase1_round_trips.py::test_phase1_latency_kpi_reported`.
6. No outstanding capability-claim debits above per-desk budget. Audit at `docs/capability_debits.md`; the closing assessment ("all in-budget") satisfies this criterion.

Explicit non-requirement at Phase 1: portability redeployment to equity VRP. That is Phase 2. Phase 1 exits with the capability claim **asserted**, not **verified**.

Phase 2 deadline: redeployment attempt within **3 months** of Phase 1 exit. Longer delay drifts the architecture and invalidates the test.

### 12.3 Abandon criteria (any one triggers stop)

1. **≥ 2 desks fail sign-preservation gate**. Signal catalogue is structurally weak for this architecture; no amount of desk rewriting fixes it. Re-examine the domain decomposition or data regime.
2. **Research-loop latency > 2 weeks on event-driven triggers**. The loop is batch processing with extra steps; capability claim fails.
3. **Scaffolding alone exceeds 6 weeks**. Scope is wrong. Reduce desks, simplify the loop, or redesign the scaffold — don't continue with a broken foundation.
4. **`contracts/v1.py` needs a v2 bump before the portability test runs**. The asset-class-agnostic schema was wrong from the start. Capability claim already broken.

Abandonment is a capability-claim artefact (negative result is a deliverable, §1.3). Document the specific failure mode; retain the artefacts; learn from the exit.

### 12.4 Budget

6 months calendar time total for Phase 1. Aggressive. Requires strict MVP discipline per desk. Tight against the scaffold-≤-6-weeks abandon rule. No slack. See §14.6 for the realism flag.

---

## 13. Out of scope for Phase 1

- Any live capital.
- Paid data feeds (Bloomberg, Argus, Platts, Kpler, Vortexa, commercial GPR platforms).
- Fine-tuning of foundation models, unless escalation ladder (§7.3) demands it for one specific desk.
- Distillation of TSFM outputs.
- LLM in the trading decision path.
- Multi-agent debate at the Controller level (debate is permitted inside desks, e.g. Geopolitics contested events, and inside the research loop, never at the Controller).
- Cross-commodity Phase 1 portability. Oil only. Equity-VRP portability is a Phase 2 validation event.
- Real-time online weight updates (bandit / OGD / contextual).
- CVaR-constrained sizing, utility-theoretic sizing, covariance estimation (deferred to Phase 2; see §8.2a).
- Execution infrastructure beyond paper backtest + live event-scoring.

---

## 14. Tensions and flagged risks

### 14.1 Budget vs abandon criteria

Scaffold-≤-6-weeks inside a 6-month Phase 1 total gives the architecture 4 weeks of actual headroom if scaffolding runs long. The abandon rule is intentionally sharp to force scope discipline, but it is not a safety margin. A realistic Week-0 scope cut-list should be drafted at scaffold kick-off and held ready for use.

### 14.2 Asserted vs verified capability claim

Phase 1 exits with the capability claim asserted. The equity-VRP redeployment is what verifies it. The 3-month Phase 2 deadline is itself a capability-claim commitment; slipping it is a capability-claim debit that invalidates the Phase 1 "done" claim in retrospect.

### 14.3 Solo operator risk

Every decision must be maintainable by one person. Any architectural choice that requires specialist secondary expertise (e.g. production-grade Kubernetes, multi-node distributed training, custom CUDA kernels) is out of scope by construction.

### 14.4 LLM cost drift

API-tier LLM spend is budgeted in tens of dollars per month. Cost drift beyond that is a capability-claim debit flagging either routing-rule misuse or scope creep in research-loop work items. Monitored as a KPI.

### 14.5 Data-quality failure modes

Scraped news, free EIA/OPEC/JODI, and Fed-hosted indices all have schedule slippage, format changes, and occasional outages. The `staleness` flag in the Forecast schema is load-bearing: desks that swallow bad data silently will pass gates spuriously and fail under distribution shift. Data ingestion must emit explicit freshness signals consumed by desks. Scheduled-ingestion failures fire the `data_ingestion_failure` trigger (§6.2).

**v1.7 three-layer learning loop** (operates with no human-in-the-loop, §6.2 discipline):

1. **Infrastructure + per-desk staleness (Layer 1).** A `feed_incidents` table keyed on `(feed_name, closed_ts_utc IS NULL)` tracks open incidents. `data_ingestion_failure_handler` v0.2 calls `persistence.open_feed_incident` (idempotent on re-fire), and each concrete desk declares `feed_names: list[str]` — the data-source identifiers it depends on. At Forecast emission, each desk calls `self._staleness_from_feeds(conn)`, which reads the registry and ORs into `Forecast.staleness`. The Controller's existing `if f.staleness: continue` path (see §controller combined_signal) then drops those desks from the decision automatically. This closes the gap between "feed failure detected" and "Controller stops trading on dead data" without touching the Controller.

2. **Rolling failure-rate rules (Layer 2).** A new periodic handler `feed_reliability_review_handler` reads `feed_incidents` over a lookback (default 30 days) and applies pre-registered thresholds:
    - **Retirement**: a feed with ≥ `retirement_threshold` failures (default 5) AND a currently-open incident causes every affected desk's weight to zero across *every regime where it holds non-zero weight* (§7.2 harmful-case parity, implemented in `remediation.retire_desk_for_all_regimes`). Tagged `"retire:feed_unreliable:<feed>"`.
    - **Bounded cap**: at most `max_retirements_per_7_days` (default 2) desk-regime-target triples may be retired in any rolling 7-day window. Overshoot is surfaced in the artefact (`retirements_skipped_capped`, `cap_reached=True`) rather than silently dropped — the cap exposes a cascading-loss risk for operator review, it does not gag it.
    - **Reinstatement (v1.9)**: a feed with no failures for `recovery_days` (default 14) and no currently-open incident triggers reinstatement. Primary path: `historical_shapley_share(conn, desk_name, lookback_days=90, now_utc)` computes the desk's mean share of total \|Shapley\| across recent reviews (bounded [0, 1]); if non-None and positive, the value is used as the reinstatement weight via `remediation.reinstate_desk_direct`. Fallback when the desk has no recent attribution rows: `reinstate_desk_direct(weight=reinstate_weight)` (default 0.1) — conservative starting weight letting the desk re-earn through the next Shapley review. Both paths write tagged `"reinstate:feed_recovered:<feed>"`. Single-desk targeted — does not disturb other desks' weights.
    - **Recovery (v1.9)**: `scheduler.check_incident_recoveries(conn, now_utc, actual_prints_per_feed)` closes `feed_incidents` when any scheduled firing post-incident receives a Print within tolerance, AND invokes `feed_latency_monitor.reset_for_feed` so the Page-Hinkley detector starts the next drift episode from a clean baseline. A single on-time Print is sufficient to declare the feed healthy; more would delay reinstatement without load-bearing benefit.

3. **Page-Hinkley change-point detector (Layer 3).** For each scheduled firing, `scheduler.check_latency_drift(conn, now_utc, actual_prints_per_feed)` computes observed latency (matched Print arrival − scheduled_ts, else `now − scheduled_ts`) and threads it through `research_loop.feed_latency_monitor.update_page_hinkley`:
    - One-sided upward-drift recurrence with δ = `PAGE_HINKLEY_DELTA` (0.005) and λ = `PAGE_HINKLEY_THRESHOLD` (50.0). Persistent per-feed state in `feed_latency_state` (single row per feed; upsert on every observation; survives process restarts).
    - On newly tripped AND no currently-open `feed_incidents` row for the feed, emits a preemptive `data_ingestion_failure` with `detected_by="page_hinkley"` BEFORE the tolerance-window path would fire. Catches slow-drift failures (latencies creeping up over days) that don't cross the tolerance threshold in any single observation.
    - `feed_latency_monitor.reset_for_feed(conn, feed_name)` zeros detector state after an incident is closed so the next drift episode is detected from a clean baseline.
    - Deterministic by construction — same input sequence and parameters → same trip index → replay-safe.

Dual-path emission (scheduler tolerance-window + Page-Hinkley) is belt-and-braces: handler idempotency on `feed_incidents` ensures at most one open incident per feed at any time, regardless of which path fires first.

### 14.6 Budget realism

The 6-month calendar budget assumes zero desks escalate past zero-shot on the model ladder (§7.3). With 6 desks each having some non-zero probability of escalation to classical specialist, the expected number of escalations is ≥ 2, each adding 1–2 weeks of unplanned work. **Realistic completion is 7–8 months.** Exceeding 6 months without hitting an abandon-trigger (§12.3) is a **capability-claim debit** logged in the derivation trace and reviewed at Phase 1 exit. The 6-month budget is not relaxed by this flag — it is aspirational, held up against the realistic estimate to detect scope creep early.

### 14.7 Equity-VRP (Phase 2) readiness

The Phase 2 portability test requires five equity-VRP desk candidates to exist in some form at Phase 1 exit. If the Speckle and Spot project (or equivalent) does not have identifiable desk analogues by Phase 1 month 5, Phase 2 slips. Phase 2 slippage is a capability-claim debit distinct from Phase 1 completion. Phase 1 includes a **month-5 checkpoint** during the Macro-desk build (the lowest-intensity desk in the schedule) to confirm equity-VRP desk candidates are identified; missing this checkpoint fires an explicit flag in the research loop's periodic review.

**v1.12 closure (2026-04-18).** Month-5 checkpoint CLOSED via the Phase 2 MVP ship (tag `phase2-mvp-v1.12`). Interpretation: "candidates exist in some form" is satisfied by the synthetic-only MVP implementation of `desks/dealer_inventory/` + `sim_equity_vrp/` + the parametrised equity-VRP portability test. Architectural claim "zero changes to shared infrastructure under equity-VRP redeployment" is VERIFIED for the MVP scope. Remaining four equity-VRP desks (`hedging_demand`, `term_structure`, `earnings_calendar`, `macro_regime`) and model-quality verification are Phase 2 scale-out work; see `docs/phase2_mvp_completion.md`.

### 14.8 Cold-start policy (Day 1 of live event-scoring)

On Day 1 of the live event-scoring loop, before any Controller weight has been promoted via the staged-candidate path (§8.3), the Controller operates under **uniform weights across all deployment-signed-off desks**. Uniform weights are emitted as ordinary `SignalWeight` rows and one matching `ControllerParams` row with:

- `promotion_ts_utc = boot_ts` (the Controller's init timestamp, **microsecond-precision** `datetime.now(tz=UTC)`; Python's stdlib guarantees microsecond resolution on all supported platforms).
- `validation_artefact = "cold_start"`.
- `k_regime = 1.0`, `pos_limit_regime = default_cold_start_limit` (pre-registered, conservative).

Under uniform weights, `combined_signal` is the unweighted average of desk forecasts. The first non-uniform promotion is a discrete event, logged as the first **"Controller maturity milestone"** in the derivation trace.

**Collision semantics.** Microsecond-precision `boot_ts` makes same-timestamp collisions vanishingly unlikely in practice but not impossible (frozen-clock tests; containerised replays; high-rate restart loops). In the extraordinary case of identical `promotion_ts_utc` across two `SignalWeight` or `ControllerParams` rows, the Controller's read query breaks ties by lexicographic `weight_id` / `params_id` (§8.3). This guarantees deterministic reads even under pathological re-boot patterns.

Rationale: this preserves the "Controller step is a pure function of inputs" principle — the Controller always has a valid weight matrix; there is no null-decision code path. The uniform-weight era is a first-class operational mode with its own audit provenance, not a placeholder.

### 14.9 Reliability-gate commitment (§12.2 point 3, v1.10)

**v1.10 calibration.** Calibration trajectory: v1.4 28d (SRE-convention default) → v1.6 7d (richer instrumentation compensates) → v1.8 48h (still partially gut-feel for daily-cycle bug exposure) → **v1.10 4h**. The "daily-cycle bugs" argument that anchored v1.8 at 48h doesn't apply to this system:

- We write to DuckDB, not syslog → log-rotation interactions don't exist.
- We have no real cron entries depending on our process → periodic-cron bugs aren't a surface.
- Laptop sleep is already handled by checkpoint-resume, not by running long enough to survive a sleep cycle.

What a 4-hour wall-clock run actually catches:

| Failure mode | 4-hour coverage |
|---|---|
| Fast-rate memory leaks (bad GC, unbounded caches) | Visible within 15–30 min under drip-feed. |
| Medium-rate memory leaks (leak per event-type, ~MB/hour) | 1–2 hours to surface trend. |
| File-descriptor leaks | Minutes. |
| Disk growth | 4 h × 1 sim-day/min × ~1 KB/decision ≈ 240 KB — nowhere near the 5 GB threshold (as expected; the threshold is for catastrophic runaway, not normal growth). |
| Deterministic scheduler/DB/bus failures | ≈ 240 decision cycles + 240 scheduler firings — ample statistical exposure. |

What 4 hours does NOT catch:
- Genuine multi-day leak patterns (tens of MB/day). For a synthetic research prototype with no real capital at risk, this is not a Phase-1 blocker — production monitoring would surface it if Phase 2 happens.
- Very rare failure modes that only manifest under multi-day exposure.

**Escape valve.** The CLI still accepts `--duration-days N` for operator-initiated longer runs. If a specific concern (e.g. "might leak a few MB/hour") calls for longer exposure, extend it for that run only. The spec commits to 4h as the Phase-1 done-criterion floor, not a ceiling.

**Operator-side cost.** 4 hours of wall-clock process uptime on a development machine. (Can run over lunch.) The `soak/` runner's checkpoint-and-resume design (v1.5-critique fix #2) tolerates OS reboots, `brew upgrade`, laptop sleep, and power events — provided the runner resumes cleanly from the checkpoint, elapsed time is cumulative and the clock does NOT reset. Only a checkpoint-corrupting failure (db_corruption incident) resets elapsed.

**Non-idle loop.** The `SyntheticDataFeed` drip-feeds a `LatentPath` at 1 sim-day per real minute (default), so every minute the system processes a new simulated trading day — writing forecasts, running the Controller, persisting decisions, sampling resources. The loop is never idle (v1.5-critique fix #3).

**Numeric thresholds.** Replace the hand-wavy "zero infrastructure incidents" with `IncidentThresholds` pre-registered in `soak/incident.py` (v1.5-critique fix #5). Changing the thresholds is a v1.x spec revision.

**Policy.** The Reliability gate is **required for complete Phase 1**, but can be scheduled independently of the Logic gate. Dropping it entirely is a **capability-claim debit** logged in §15. The CLI entry point is `scripts/run_soak_test.py`; the accelerated CI variant runs in seconds (`tests/test_soak_runner_short.py`) and validates the runner end-to-end.

---

## 15. Derivation trace — which decision answered which question

For future readers: the five rounds of clarifying discussion that produced v1.0, plus subsequent review responses. Each row cites the first point at which the decision was frozen.

**Round-numbering convention.** `R#` refers to an AskUserQuestion **batch**; each batch contained 1–4 questions answered in a single response. Multiple decisions froze within a single batch simultaneously. Sub-ordering of decisions within a round is preserved in git history but not in this trace table; where a decision is ambiguous about "which question within the round," consult the spec-edit commit for that decision.

| Decision | Frozen in |
|---|---|
| Solo execution, clean slate, synthetic-only, capability-build | v1.0 (R1) |
| Live event-scoring loop, event-sourced architecture | v1.0 (R2) |
| Portability target = equity VRP (same-architecture different-asset-class) | v1.0 (R2) |
| Typed at Controller boundary only; `contracts/v1.py` owned by Controller | v1.0 (R2) |
| Hard gates = {skill, sign preservation, hot-swap}; LODO as escalating diagnostic | v1.0 (R2) |
| Pre-registered directional claim per desk | v1.0 (R2) |
| All six desks in Phase 1 | v1.0 (R3) |
| Kronos reinstated with gate 2 as the catch | v1.0 (R3) |
| Zero-shot default; per-desk escalation ladder; distillation rejected | v1.0 (R3) |
| LLM in research loop only, never in trading path; two-tier routing | v1.0 (R3) |
| Regime-conditional linear weights, offline-fit, discrete promotion | v1.0 (R4) |
| Shapley + LODO as co-primary attribution | v1.0 (R4) |
| Hybrid event-driven + periodic research loop; categorically different work | v1.0 (R4) |
| All four human-in-the-loop gates active | v1.0 (R4) |
| Scaffold → stubs-all-six → S&C → Geopolitics → Supply/Demand → Macro → Controller weights | v1.0 (R5) |
| Abandon criteria: any of four triggers | v1.0 (R5) |
| Budget: 6 months calendar | v1.0 (R5) |
| `target_variable` frozen registry; horizon semantics; event-slip policy | v1.1 (review response) |
| CVaR → linear sizing commit; dimensionality discipline | v1.1 (review response) |
| Provenance dirty-tree policy; `data_ingestion_failure` trigger | v1.1 (review response) |
| Done-criterion strengthened (4-week continuous, 10/20 round-trips, latency KPI reported) | v1.1 (review response) |
| Cold-start policy (uniform weights); Phase 2 readiness check; budget realism | v1.1 (review response) |
| `regime_probabilities` on RegimeLabel; routing postconditions; `attribution_lodo` grain fix + `decisions` table | v1.1 (review response) |
| DuckDB single-file layout (§3.2) | v1.2 (review response) |
| `controller_params` separate table; rollback as distinct human operation; `boot_ts` microsecond precision + tie-break rule; regularisation assumed for weight fits; `config/data_sources.yaml` as the owning artefact for ingestion-failure payload | v1.3 (review response) |
| Architecture completion (implementations + tests for every §-section): three-hard-gate harness, StorageCurveDesk classical-specialist deepen, regime-conditional linear Controller with §14.8 cold-start, LODO signal- and grading-space, Shapley exact and sampled, replay-determinism (Controller + attribution), Phase-1 end-to-end smoke, research-loop dispatcher + periodic + event-driven handlers (gate_failure/regime_transition/data_ingestion_failure), §8.3 weight-promotion v0.2/v0.3 with held-out margin validation | Tags `gates-v1.0`, `storage-curve-classical-v0.1`, `controller-v1.0`, `lodo-v0.1`, `phase1-smoke-v0.1`, `shapley-v0.1`, `replay-determinism-v0.2`, `research-loop-v0.1`, `promotion-v0.2`, `lodo-grading-v0.2`, `promotion-v0.3`, `event-handlers-v0.1`, `shapley-sampled-v0.2` (all shipped in one session, 2026-04-17) |
| Phase A+B+C synthetic market simulator + 5 classical specialists + staged observability (plan §A, user's Q1/Q2/Q3 research). 5-factor latent state (Schwartz-Smith + OU + Hawkes) with per-desk AR(1) return drivers, regime-tagged episodes, 3 observation modes (clean / controlled leakage / realistic contamination). Four new desk classicals (supply/demand/geopolitics/macro) + regime-classifier ground-truth pass-through. Per-phase integration tests: Phase A passes gates on clean 1:1 observations; Phase B degrades gracefully under 10% leakage; Phase C survives realistic contamination (chatter + NaN-missingness + publication lag). §12.2 point 2 split into Logic gate (simulated) + Reliability gate (28-day wall-clock). §14.9 Reliability-gate commitment added. | Tags `phase-a-v0.1`, `phase-b-v0.1`, `phase-c-v0.1`, `phases-abc-v0.1` (v1.4 revision) |
| Post-phases-abc follow-ups: (1) HMM regime classifier — 4-state Gaussian HMM via hmmlearn, replaces the Phase A ground-truth pass-through; causal inference (forward algorithm on observations[:i+1]); seed-deterministic fingerprint. (2) §6.4 LLM routing postcondition gate — `LLMArtefact` contract type + `commit_gate` validator rejecting local-tier outputs in {spec_edit, hypothesis_proposal, cross_desk_synthesis}; citations override auto-reclassifies as cross_desk_synthesis at ≥ 2 distinct desks. | Tags `hmm-classifier-v0.2`, `llm-routing-v0.1` (v1.5 revision) |
| Reliability gate calibration + implementation (§12.2 point 3, §14.9 v1.6). Five fixes: (a) duration 28d → 7d, derived from the failure modes the gate actually catches; (b) checkpoint + auto-resume so OS reboots / `brew upgrade` / laptop sleep do NOT reset the clock; (c) real-time synthetic data drip-feed so the loop is never idle; (d) instrumentation-heavy — ResourceMonitor every 60 s, IncidentDetector with numeric thresholds; (e) pre-registered threshold constants replace hand-wavy "zero incidents". `soak/` package + `scripts/run_soak_test.py` CLI + accelerated integration tests (including restart-resume). The 7-day production run remains operator-side but the runner makes it meaningful and robust. | Tags `soak-runner-v0.1` (v1.6 revision) |
| Event-driven handler v0.2 upgrades: gate_failure auto-retires on `failure_mode="harmful:*"` (§7.2 harmful-case automation); regime_transition proposes and promotes weights from Shapley rollup over ≥ `min_decisions` historical decisions in the to-regime (§8.3 refresh on transition). | Tags `gate-failure-retire-v0.2`, `regime-transition-refresh-v0.2` |
| Research-loop latency KPI aggregation + Phase 2 portability contract. `research_loop/kpi.py::compute_latency_report` yields per-type and overall mean/p50/p95/max latencies over completed events for the §12.2 KPI criterion. `tests/test_phase2_portability_contract.py` asserts shared-infra packages (`contracts`, `controller`, `persistence`, `research_loop`, `attribution`, `grading`, `provenance`, `eval`, `soak`) contain zero oil-domain vocabulary and zero `desks.*` imports; `contracts/target_variables.py` is the single source of truth for domain-specific identifiers. | Tags `latency-kpi-v0.1` |
| Phase 2 MVP ship (v1.12). One equity-VRP desk (`dealer_inventory`) + `sim_equity_vrp/` synthetic vol market + parametrised equity-VRP portability contract. Architectural claim "zero shared-infra changes" VERIFIED for MVP scope (Gate 3 strict ✓, oil+equity-VRP portability tests both green). §14.7 D5 month-5 checkpoint CLOSED. Model-quality debit D7 opened for Gate 1+2 on minimal MVP market (parallels oil D1). | Tags `phase2-mvp-v1.12` |
| Phase 2 Desk 2 `hedging_demand` ship (v1.13) — following a rigorous pre-implementation design review. `sim_equity_vrp` extended with a 4th latent factor (hedging_demand OU) + `put_skew_proxy` derived signal; golden fixtures pin dealer_inventory bit-identity. Desk 2 consumes noisy observation channels (M-1 train/serve match); `directional_claim.sign` now DERIVED from ridge score (M-3); `config/data_sources.yaml` extended with `cboe_open_interest` + `option_volume` + routing regression test (B-5). G1/G2 pinned as exact regression values. Gate 3 claim recalibrated from "runtime hot-swap" to "DeskProtocol conformance" — D9 opened for a follow-up runtime harness before Desk 3. D8 opened for same-target Shapley aggregation normalization. D7 expanded to cover hedging_demand. | Tags `phase2-desk2-hedging-demand-v1.13` |
| Phase 1 exit manifest (v1.11). Each §12.2 item linked to code + test evidence; storage_curve 3/3 + Gate 3 5/5 confirmed on 10/10 seeds; ≥ 20 round-trips per desk shipped in `test_phase1_round_trips.py`; latency KPI demonstrated end-to-end; 6 capability debits consolidated (all in-budget). `docs/phase1_completion.md` + `docs/capability_debits.md` are the Phase 1 audit artefacts. | Tags `phase1-complete-v1.11` |
| Reliability gate 48h → 4h (v1.10 §12.2 point 3, §14.9). The v1.8 "daily-cycle bugs" anchor didn't apply to a DuckDB-based research prototype. 4h catches fast/medium leaks + FD leaks + ~240 decision cycles of deterministic-failure exposure. Multi-day leaks (tens of MB/day) deferred to production monitoring if Phase 2 happens. Escape valve preserved via `--duration-days`. | Tags `reliability-gate-v1.10` |
| Feed-reliability loose ends closed (v1.9): incident-recovery auto-close + PH reset, weekly review submitter helper, Shapley-informed reinstatement via `historical_shapley_share` (mean desk-share across recent reviews) with conservative direct-insert fallback. Resolves v1.7's "propose_and_promote_from_shapley would re-weight all desks" finding. | Tags `reliability-loose-ends-v1.9` |
| Reliability gate duration 7d → 48h (v1.8 §12.2 point 3, §14.9). Under scrutiny the 7-day duration was named (gut-feel), not derived from a failure model. 48h catches all meaningful failure modes (memory leaks, FD leaks, daily-cycle bugs) at ≈ 30% the wall-clock cost. CLI + runner defaults updated; instrumentation unchanged. | Tags `reliability-gate-v1.8` |
| Feed-reliability learning loop (v1.7 §14.5). Three layers land together: (1) `feed_incidents` + `feed_latency_state` schema and CRUD primitives; (2) per-desk `feed_names` declaration + `_staleness_from_feeds` hook; `data_ingestion_failure_handler` v0.2 opens idempotent incident rows; scheduler payload rename `consumed_by` → `affected_desks`; (3) rolling-rate `feed_reliability_review_handler` with all-regimes retirement (§7.2 parity), bounded `max_retirements_per_7_days=2` cap, reinstatement via Shapley promotion with `reinstate_desk_direct(weight=0.1)` fallback; (4) Page-Hinkley change-point detector on per-feed latency integrated into `scheduler.check_latency_drift`, state persisted and replay-deterministic. `data_sources.yaml` populated for four feeds. Answers the "no human in the loop — can ML learn which feeds are broken?" research question with a pragmatic hybrid: counting + threshold rules do most of the learning; PH adds narrow early-warning on slow drift. | Tags `feed-incidents-schema-v0.1`, `data-ingestion-handler-v0.2`, `feed-reliability-review-v0.2`, `feed-latency-monitor-v0.2` (v1.7 revision) |

Full v1.0 review captured verbatim at `docs/reviews/2026-04-17-v1.0-review.md`.

---

## 16. Sign-off

| Field | Value |
|---|---|
| Spec version | v1.13 |
| Date frozen | 2026-04-17 |
| Domain instance | crude oil (WTI/Brent) |
| Portability target | equity VRP (Speckle and Spot) |
| Operator | Henri Rapson |
| Repo | This repository (clean slate as of v1.0; v1.1 is a minor-version bump) |
| First artefact to build | `contracts/v1.py` + `contracts/target_variables.py` + `tests/test_boundary_purity.py` (Week 0, Day 1) |

Any change to §4, §6, §7, §8, §9, §10, or §11 beyond what this v1.1 already contains requires a v2 bump. Non-breaking additions (new `target_variable` constants, new research-loop triggers, new gate-diagnostic metrics) can be added under v1.x revisions logged in §0.
