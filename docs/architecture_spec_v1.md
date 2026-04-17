# Multi-Desk Trading Architecture — Specification v1

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

---

## 1. Scope, objective, and discipline

### 1.1 Objective

Build a multi-desk, agent-led, coordination architecture for systematic trading research. The deliverable is the **architecture** — contracts, orchestration, research loop, attribution — not a P&L number. The architecture is considered successful if it redeploys to an unrelated asset class (equity VRP, the Speckle and Spot project) with zero changes to shared infrastructure.

P&L is diagnostic, not the objective. Per-desk skill is a quality signal about the architecture's usefulness; it is not what is being optimised.

### 1.2 Scope

- **Data/capital regime**: synthetic / research-only. Free public data sources only (EIA 914/STEO/WPSR, OPEC MOMR text, JODI, CFTC COT, Caldara-Iacoviello GPR via Fed, scraped news, OFAC/HMT/EU sanctions downloads, Google Trends). No Bloomberg, Argus, Platts, Kpler, Vortexa. No live capital. No small-live phase. Validation terminus is paper backtest + live event-scoring loop on post-pretraining-cutoff data.
- **Model stack**: OSS-first. Closed models (Claude, GPT) only in the research loop, and only for reasoning-heavy tasks. Zero-shot foundation-model usage as default (see §9 for the per-desk escalation ladder).
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
│                                      attribution, model registry)            │
└──────────────┬──────────────────────────────────────────────────────────────┘
               │
               ├──────────────► Grading  (pure fn of Forecast × Print)
               │
               ├──────────────► Attribution  (LODO online, Shapley weekly)
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
- **Grading is a pure function.** `Grade = grade(Forecast, Print)`. No hidden state; re-running grading on historical data reproduces the original grades byte-identically.
- **Replay is a first-class operation.** Any historical window can be re-grading or re-attributed from persistence. Input snapshot hashes in the Forecast provenance block permit exact reconstruction of what the desk saw at emission time.

### 3.2 Persistence

Primary store: DuckDB. File per table under `data/duckdb/`:

| Table | Rows | Indexed on |
|---|---|---|
| `forecasts` | one per emit() | `(desk_name, emission_ts_utc, target_variable, horizon_id)` |
| `prints` | one per realised outcome | `(target_variable, realised_ts_utc, vintage_of)` |
| `grades` | one per (Forecast × Print) match | `(forecast_id, grading_ts_utc)` |
| `signal_weights` | one per promoted weight matrix | `(regime_id, promotion_ts_utc)` |
| `attribution_lodo` | one per print, per desk | `(print_id, desk_name)` |
| `attribution_shapley` | one per weekly review | `(review_ts_utc, desk_name)` |
| `research_loop_events` | one per trigger firing or periodic review | `(event_type, start_ts_utc)` |
| `model_registry` | one per deployed model version | `(desk_name, model_name, version, registration_ts_utc)` |
| `regime_labels` | one per classifier emit | `(classification_ts_utc)` |

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

Desks MUST emit with explicit staleness / confidence flags when upstream data is stale or missing. A broken feed is a Forecast with `staleness=True` and expanded uncertainty — never silent reuse of old data.

---

## 4. Contract layer — `contracts/v1.py`

### 4.1 Ownership and purpose

One frozen Python module. Owned by the Controller, not by any desk. Imported by every desk and by the bus. No desk may modify it. Breaking changes require a major-version bump and a new `contracts/v2.py` module; v1 and v2 can coexist only during a migration window, with a clear deprecation schedule.

Validation is enforced at the bus on publish, not trusted at the desk. A desk emitting a malformed Forecast fails loudly; the attribution DB never sees it.

### 4.2 Semantic conventions

- Units are in field names (`price_usd_bbl`, not `price`). The Forecast schema itself is unit-agnostic — domain-specific units live inside `target_variable` metadata.
- Timestamps are always timezone-aware UTC. Naive timestamps are forbidden at the boundary.
- Horizons are typed as a tagged union, not a free-form string (see below).
- Uncertainty is always expressed; a point forecast carries a degenerate (zero-width) interval, not a missing value.
- Directional claim is pre-registered in the desk spec and echoed in every Forecast. Desks that cannot articulate a directional claim cannot emit Forecasts.

### 4.3 Core types

```python
# contracts/v1.py

from datetime import datetime, timedelta
from enum import Enum
from typing import Literal, Union
from pydantic import BaseModel, Field, ConfigDict


class Provenance(BaseModel):
    """Identifies who/what produced this object and how to reconstruct it."""
    model_config = ConfigDict(frozen=True)

    desk_name: str
    model_name: str
    model_version: str       # SemVer: MAJOR.MINOR.PATCH
    input_snapshot_hash: str # hex digest of the ordered input-tuple
    spec_hash: str           # hex digest of the desk spec at emission time
    code_commit: str         # git SHA of the desk code at emission time


class ClockHorizon(BaseModel):
    model_config = ConfigDict(frozen=True)
    kind: Literal["clock"] = "clock"
    duration: timedelta


class EventHorizon(BaseModel):
    """For event-driven targets (next-FOMC, next-OPEX, next-CFTC-COT, etc.)."""
    model_config = ConfigDict(frozen=True)
    kind: Literal["event"] = "event"
    event_id: str            # stable identifier for the event
    expected_ts_utc: datetime  # best-estimate firing time


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
    target_variable: str     # e.g. "wti_front_month_close", "vrp_sp500"
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
    realised_ts_utc: datetime
    target_variable: str
    value: float
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


class SignalWeight(BaseModel):
    """A row of the regime-conditional weight matrix.

    Controller state is a collection of these, indexed by (regime_id, desk_name,
    target_variable). Promotion events append new rows with a new promotion_ts;
    the Controller reads the most recent row per (regime, desk, target) tuple.
    """
    model_config = ConfigDict(frozen=True)

    weight_id: str
    regime_id: str
    desk_name: str
    target_variable: str
    weight: float
    promotion_ts_utc: datetime
    validation_artefact: str  # path to the held-out validation result


class RegimeLabel(BaseModel):
    """Opaque regime label emitted by the regime classifier.

    Deliberately opaque: no contango/backwardation, no bull/bear, no
    oil-specific semantics cross the boundary. The Controller uses the
    string id as a key; its meaning lives inside the classifier.
    """
    model_config = ConfigDict(frozen=True)

    classification_ts_utc: datetime
    regime_id: str            # e.g. "regime_low_vol_bullish"
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
- No commodity-specific fields. `wti_front_month_close` is a valid `target_variable` (a string); `wti_price: float` as a typed field is not.
- No raw model outputs. A desk that produces a multi-modal posterior must summarise to a point estimate + uncertainty interval for emission.
- No aliasing. Every Forecast has exactly one `target_variable` and exactly one `horizon`. A desk producing a 1-week and 1-month forecast emits two Forecast objects, not one with two fields.

### 4.5 Test: `tests/test_boundary_purity.py`

Imports only `contracts/v1.py`, the bus, the Controller, and the grading harness. Mocks every desk as a simple `emit()`-producing function that returns valid Forecast objects. Asserts: Controller runs to completion across a synthetic release-calendar replay. If this test ever needs to import a desk's internals to pass, the boundary has drifted; the capability claim is broken.

---

## 5. Desks — interface and per-desk skeleton

### 5.1 Desk contract

Every desk implements the following minimum interface:

```python
# Convention; no abstract base class required
class Desk:
    name: str                   # unique, e.g. "storage_curve"
    spec_path: str              # path to the desk spec document
    emit_target_variables: list[str]
    emit_horizons: list[Horizon]

    def on_schedule_fire(self, now_utc: datetime) -> list[Forecast]:
        """Called by the scheduler on the desk's emission cadence."""

    def on_trigger(self, event: ResearchLoopEvent) -> list[Forecast] | None:
        """Optional: react to a research-loop trigger (e.g. rerun after spec update)."""
```

Desk internals are unconstrained. PyMC, CatBoost, Kronos inference, LLM extraction pipelines, classical BVAR — all are valid.

### 5.2 Per-desk spec document (required before build)

Each desk has a spec document at `desks/<name>/spec.md`. Required sections:

1. **Target variables and horizons** — exactly what the desk emits.
2. **Directional claim per variable** — positive / negative, with justification referencing a dev-period Spearman or equivalent.
3. **Pre-registered naive baseline** — random walk, climatology, persistence, or explicit alternative, chosen BEFORE any model is fit.
4. **Model ladder** — zero-shot → classical specialist → borrowed-compute fine-tune (§9).
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
| 5 | `macro` | Mixed-frequency BVAR, Markov-switching + HMM, TabPFN-v2, factor model for DXY decomposition | Emits macro regime conditioning info as a Forecast, NOT as a RegimeLabel (the regime classifier is Controller-owned, see §8). |
| 6 | `regime_classifier` | HDP-HMM + online Bayesian change-point | Owned by the Controller, not a trading desk. Emits RegimeLabel events. Consumes desk outputs, never raw domain data. |

Desk 6 is listed separately because its contract is different — it emits RegimeLabel, not Forecast — and it is domain-blind by construction (inputs are the vector of desk outputs). Under equity-VRP redeployment, desks 1–5 are fully replaced; desk 6 redeploys with zero changes.

---

## 6. Research loop

### 6.1 Paths and KPIs

The research loop has two paths that do **categorically different work** and carry different KPIs.

| Path | Work | KPI |
|---|---|---|
| Event-driven | Reactive: gate failure RCA, regime-transition handling, attribution anomaly investigation, correlation-shift investigation, desk-staleness response, Controller-commissioned requests | Latency from trigger fire to artefact produced |
| Periodic (weekly) | Proactive: experiment backlog grooming, capability review, specification drift check, abstraction audit, cross-print pattern synthesis, forward-looking hypothesis generation | Completion rate (did the review run?); output quality (did it produce ≥1 actionable item?) |

Event-driven path **preempts** periodic. Periodic pauses on event fire, handles the event, resumes with post-event state. No parallel processing (event work is minutes to hours; periodic is bounded to hours).

### 6.2 Event-driven triggers (pre-registered)

The trigger list is itself a contract. Adding a new event type is a design change, logged as a v1.x revision; it is not an ad-hoc addition.

| Trigger | Fires when | Default priority |
|---|---|---|
| `gate_failure` | Any desk fails skill, sign-preservation, or hot-swap gate | 0 (highest) |
| `regime_transition` | Regime classifier flags transition with P > 0.7 | 1 |
| `weight_staleness` | Realised skill < pre-registered threshold for N days | 2 |
| `attribution_anomaly` | LODO or Shapley contribution moves outside per-desk pre-registered tolerance band | 2 |
| `correlation_shift` | Pairwise desk-output correlation crosses pre-registered threshold | 3 |
| `desk_staleness` | Desk emits `staleness=True` or `confidence < threshold` | 3 |
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

Two tiers, pre-registered routing rules. Routing decisions logged per invocation; overrides (local fell back to API or vice versa) tracked as a quality metric.

| Tier | Model class | Use | Expected volume |
|---|---|---|---|
| Local | Q4-quantised 7–8B (Mistral-7B, Qwen-2.5-7B, Llama-3.1-8B) via MLX or llama.cpp | Daily log summarisation, structured extraction from desk outputs, attribution-DB querying, pattern matching across regime history | High (hundreds of calls/week) |
| API | Claude Opus/Sonnet, GPT-4o | Experiment design from anomaly, desk-spec revision drafting, RCA on gate failures, cross-desk synthesis | Low (tens of calls/week) |

**Routing rules** (pre-registered):
- Anything that writes to a desk spec → API.
- Anything that proposes a hypothesis for experimental testing → API.
- Anything that interprets cross-desk patterns → API.
- Everything else → local.

Budget target: API spend in the tens of dollars per month in research mode. Overruns are logged as capability-claim debits.

### 6.5 LLM is forbidden in the trading-decision path

The LLM is never in the Controller's decision flow. This is architectural, not optional. Reintroducing it contaminates attribution (stochasticity, silent-model-version changes, context-window dependence), breaks portability (LLM judgement does not redeploy as shared infrastructure), and violates the "Controller owns no domain opinions" principle. Research-loop LLM output is staged (spec revisions, weight-update proposals) and promoted to the decision path only via the human-gated promotion events (§12).

---

## 7. Hard gates

### 7.1 The three hard gates

A desk cannot be promoted into the Controller's input set until it passes all three gates on test data. A desk that fails any gate after promotion is a candidate for retirement (see §12 for the adjudication path).

**Gate 1 — Skill vs pre-registered naive baseline.**

The desk beats a pre-registered naive baseline (random walk, climatology, persistence, or explicit alternative) on its primary forecast metric (RMSE, Brier, log-score as appropriate) on test data. The baseline is chosen **BEFORE** the desk's model is fit; post-hoc baseline-shopping invalidates the gate.

**Gate 2 — Dev→test sign preservation.**

Pre-registered Spearman rank correlation of the desk's directional-claim-aligned score against the forward-realized target, computed on dev and on test. Sign must agree on both periods.

This is the Kronos-RCA gate. Kronos showed +0.43 Spearman on dev and −0.23 on test; the architecture's core commitment is that this kind of failure is caught at stage 1 not stage 5. Sign-flip between dev and test is the signature of spurious correlation — unfixable by sizing, re-weighting, or Controller adjustment. Hard gate, tested early, no appeal.

**Gate 3 — Hot-swap against stub.**

A stub desk emitting valid Forecast objects with null signal (directional claim = "none", calibrated uncertainty, staleness = True) can be swapped in place of the real desk without breaking the Controller. The Controller runs to completion, weights degenerate to the matrix's baseline, and the grading harness continues processing. Fail → desk is reaching into Controller internals or Controller is pattern-matching on specific desk outputs; both are architectural bugs.

### 7.2 LODO as escalating diagnostic

Leave-one-desk-out ablation is run continuously (on every print) but is not a hard gate by default. Three outcomes:

| Outcome | Interpretation | Action |
|---|---|---|
| Desk harmful | Controller strictly better without the desk (pre-registered window, statistical significance) | **Hard-gate retire** — the desk is actively damaging decisions |
| Desk redundant | Controller indifferent (strictly equal metrics within tolerance) | Warning-track flag; after N Controller revisions or M months, if still redundant, retire |
| Desk unused | Controller underweight the desk but using it | Diagnostic only; Controller maturity may change this |

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

1. Read the current RegimeLabel (most recent `regime_classifier` emit).
2. Look up the weight row for the regime.
3. Compute `combined_signal = sum(weight × desk_forecast)` across all desks.
4. Apply CVaR-constrained portfolio sizing (regime-conditional covariance) to translate combined_signal into position sizes.
5. Emit decision event to the audit log.

All of the above is a pure function of inputs. Replay on historical window reproduces the original decision byte-identically.

### 8.3 Weight promotion

Controller weights never update in real time. The update path is:

1. Prints land → grades computed per Forecast per desk → attribution DB updated. **Controller weights unchanged.**
2. Research loop (either event-driven or periodic) queries the attribution DB, asks: "are the current regime weights still skill-preserving?"
3. If not, the loop proposes a new weight matrix — a new `SignalWeight` row bundle — staged as a candidate version.
4. The candidate is validated against recent held-out data on the pre-registered promotion metric.
5. If it beats the current matrix by a pre-registered margin, it is presented to the human for approval (human-in-the-loop gating, §11).
6. Upon approval, the candidate is promoted — new `SignalWeight` rows appended to the DB with new `promotion_ts_utc`. The Controller reads the most recent row per (regime, desk, target) tuple; the new weights take effect on the next Controller invocation.

Promotion is a discrete event, logged as a capability artefact. The attribution DB permits post-hoc comparison of the pre- and post-promotion weight performance on the same print history.

### 8.4 Portability

Under equity-VRP redeployment, the Controller redeploys with **zero code changes**. What changes:

- The weight matrix is re-fitted (equity-VRP desks, equity-VRP regimes, equity-VRP historical data).
- The regime classifier's internal HDP-HMM is retrained on equity-VRP desk outputs.
- Desks 1–5 are fully replaced.

What does not change:
- `contracts/v1.py`
- The bus
- The grading harness
- The attribution DB schema (though its contents are domain-specific)
- The research-loop trigger list (the events are asset-class-agnostic)
- The Controller's decision flow

This is the capability-claim acceptance test.

---

## 9. Attribution

Two methods, co-primary for their respective questions.

### 9.1 LODO — retirement and harm detection

Run on every print (or batch of prints per grading cycle). For each desk:

1. Recompute the Controller's decision stream with that desk's Forecasts replaced by the stub (null signal).
2. Recompute the grading stream.
3. Diff the two streams on the pre-registered LODO metric (typically per-decision squared error or PnL attribution).

Per-desk LODO contributions land in the `attribution_lodo` table.

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

### 10.2 Method

- Primary: hierarchical Dirichlet process HMM (HDP-HMM). Non-parametric regime count; no fixed K.
- Secondary: online Bayesian change-point detection (Adams & MacKay 2007) for fast-break identification.

Emits `RegimeLabel` events on each classification cycle. Regime IDs are opaque strings (`regime_7f3a`, not `regime_contango`).

### 10.3 Gates

The regime classifier is itself a desk (§5.3 desk 6) and must pass:
- **Skill**: regime labels distinguishable from random on a pre-registered held-out period (e.g. forward-window-realised-vol differs across regime labels with p < 0.05 under permutation).
- **Sign preservation**: directional claim on regime transitions (e.g. "transitions to regime X are associated with higher forward realised vol") must hold dev-to-test.
- **Hot-swap**: replaceable with a trivial one-regime classifier without breaking the Controller (Controller degenerates to the unconditional weight matrix; still functions).

---

## 11. Human-in-the-loop gating

Four approval points, all active:

1. **Desk-spec changes require human approval.** The research-loop LLM can draft revisions, but changes merge only on human review. Protects against silent desk-spec drift that would show up as degraded attribution months later.
2. **Controller-weight updates auto-promote; human sees audit log.** Given the staged-candidate + pre-registered-margin + held-out-validation path, auto-promotion is acceptable; the human reviews the daily/weekly audit summary. Any promotion event can be rolled back manually by writing a superseding `SignalWeight` row.
3. **Initial desk deployment requires human sign-off.** A desk enters the Controller input set only after human reviews the dev-period sign-preservation gate results, the skill-gate results, and the hot-swap test. New-desk addition is deliberate, not automatic.
4. **Gate-failure-triggered retirements require human adjudication.** If a desk fails skill or sign-preservation or (post-maturity) LODO-harm, retirement is proposed by the system but requires human confirmation. Prevents false-positive retirements on transient data-quality issues.

---

## 12. Phase 1 — sequence, done-criterion, abandon rules

### 12.1 Sequence

1. **Week 0 — scaffold**. `contracts/v1.py`, bus with validation, DuckDB schema, grading harness, release-calendar scheduler, input-snapshot hasher, `tests/test_boundary_purity.py`, `tests/test_replay_determinism.py`. No desk work until scaffold is green.
2. **Weeks 1–2 — stubs for all six desks**. Each stub passes the hot-swap gate (valid boundary contract) and fails the skill gate (null signal). End-to-end pipeline runs against six stubs; attribution DB records zero meaningful contribution from any desk; research-loop triggers are injectable via synthetic Forecasts and fire correctly.
3. **Desk 1 — Storage & Curve deepen**. Highest novel-tech content (Kronos, DNS + LSTM, functional change-point); earliest and cheapest failure mode; most informative about TSFM validation approach.
4. **Desk 2 — Geopolitics deepen**. Heterogeneous tech stack (LLM extraction + event-driven pipelines); stress-tests LLM two-tier routing and structured-output validation.
5. **Desks 3 & 4 — Supply + Demand in parallel**. Shared data-engineering work reduces duplication.
6. **Desk 5 — Macro deepen**. Classical econometric stack; lowest risk; benefits from mature scaffolding.
7. **Controller weight matrix — final step**. Regime-conditional matrix fitted on attribution data from the mature pipeline. Mechanical step: every prior validation event already ran against the Controller skeleton with uniform weights.

### 12.2 Done-criterion

Phase 1 is complete when: all six desks pass their three hard gates on test-set replay; live event-scoring loop has closed ≥ 1 full round-trip per desk; no outstanding capability-claim debits above per-desk budget.

Explicit non-requirement at Phase 1: portability redeployment to equity VRP. That is Phase 2. Phase 1 exits with the capability claim **asserted**, not **verified**.

Phase 2 deadline: redeployment attempt within 3 months of Phase 1 exit. Longer delay drifts the architecture and invalidates the test.

### 12.3 Abandon criteria (any one triggers stop)

1. **≥ 2 desks fail sign-preservation gate**. Signal catalogue is structurally weak for this architecture; no amount of desk rewriting fixes it. Re-examine the domain decomposition or data regime.
2. **Research-loop latency > 2 weeks on event-driven triggers**. The loop is batch processing with extra steps; capability claim fails.
3. **Scaffolding alone exceeds 6 weeks**. Scope is wrong. Reduce desks, simplify the loop, or redesign the scaffold — don't continue with a broken foundation.
4. **`contracts/v1.py` needs a v2 bump before the portability test runs**. The asset-class-agnostic schema was wrong from the start. Capability claim already broken.

Abandonment is a capability-claim artefact (negative result is a deliverable, §1.3). Document the specific failure mode; retain the artefacts; learn from the exit.

### 12.4 Budget

6 months calendar time total for Phase 1. Aggressive. Requires strict MVP discipline per desk. Tight against the scaffold-≤ 6-weeks abandon rule. No slack.

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

Scraped news, free EIA/OPEC/JODI, and Fed-hosted indices all have schedule slippage, format changes, and occasional outages. The `staleness` flag in the Forecast schema is load-bearing: desks that swallow bad data silently will pass gates spuriously and fail under distribution shift. Data ingestion must emit explicit freshness signals consumed by desks.

---

## 15. Derivation trace — which decision answered which question

For future readers: the five rounds of clarifying discussion produced these locks. Each is cited as the first point at which the decision was frozen.

| Decision | Frozen in round |
|---|---|
| Solo execution, clean slate, synthetic-only, capability-build | R1 |
| Live event-scoring loop, event-sourced architecture | R2 |
| Portability target = equity VRP (same-architecture different-asset-class) | R2 |
| Typed at Controller boundary only; `contracts/v1.py` owned by Controller | R2 |
| Hard gates = {skill, sign preservation, hot-swap}; LODO as escalating diagnostic | R2 |
| Pre-registered directional claim per desk | R2 |
| All six desks in Phase 1 | R3 |
| Kronos reinstated with gate 2 as the catch | R3 |
| Zero-shot default; per-desk escalation ladder; distillation rejected | R3 |
| LLM in research loop only, never in trading path; two-tier routing | R3 |
| Regime-conditional linear weights, offline-fit, discrete promotion | R4 |
| Shapley + LODO as co-primary attribution | R4 |
| Hybrid event-driven + periodic research loop; categorically different work | R4 |
| All four human-in-the-loop gates active | R4 |
| Scaffold → stubs-all-six → S&C → Geopolitics → Supply/Demand → Macro → Controller weights | R5 |
| Done-criterion: all six desks gate-pass + loop closed once per desk | R5 |
| Abandon criteria: any of four triggers | R5 |
| Budget: 6 months calendar | R5 |

---

## 16. Sign-off

| Field | Value |
|---|---|
| Spec version | v1.0 |
| Date frozen | 2026-04-17 |
| Domain instance | crude oil (WTI/Brent) |
| Portability target | equity VRP (Speckle and Spot) |
| Operator | Henri Rapson |
| Repo | This repository (new, clean slate as of v1.0) |
| First artefact to build | `contracts/v1.py` + `tests/test_boundary_purity.py` (Week 0, Day 1) |

Any change to §4, §6, §7, §8, §9, §10, or §11 requires a v2 bump. Non-breaking additions can be added under v1.x with an entry in §0.
