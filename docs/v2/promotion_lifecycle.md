# v2 promotion lifecycle

**Status**: D3 paper artefact. Read-only.
**Tag**: `v2-lifecycle-0.1`
**Scope**: every v2 desk, every v2 family, every v2 model-class introduction.

---

## 1. What this document is

Defines the **states** a desk or family may occupy, the **acceptance
layers** that must be satisfied to transition between states, and the
**demotion / expiry** rules that move artefacts backwards. Companion
artefact to `governance_model.md` (challenge mechanisms) and
`v2_decision_contract.md` + `v2_data_contract.md` (what is evaluated).

---

## 2. State machine

```
        S0                S1                S2               S3
     concept   ────►   PIT research   ────► validated ────► decision
                                            model           candidate

         │                   │                 │                │
         │                   │                 │                ▼
         │                   │                 │               S4
         │                   │                 │            shadow
         │                   │                 │              live
         │                   │                 │                │
         │                   │                 │                ▼
         │                   │                 │               S5
         │                   │                 │         constrained
         │                   │                 │          production
         │                   │                 │                │
         │                   │                 │                ▼
         │                   │                 │               S6
         │                   │                 │            scaled
         │                   │                 │         production
         │                   │                 │
         └───────────────────┴─────────────────┴── demotion ◄───┘
```

Forward arrows are **promotions** and require the minimum challenge stack
defined in `governance_model.md §1.1`. Demotions are **unconditional** and
require no challenge ceremony — they are a safety primitive, not a review.

---

## 3. State definitions

### S0 — Concept
- **What exists**: a mechanism memo naming the economic channel, the
  observable that identifies it, and the hypothesised sign/magnitude.
- **No code required** beyond stubs. No data ingestion required.
- **Entry requirement**: none.
- **Exit to S1**: mechanism memo reviewed by author against
  `v2_decision_contract §7 Forbidden` (no desk whose mechanism cannot be
  observed from decision-time data).

### S1 — PIT research
- **What exists**: a vintage-safe dataset + a benchmark pack. The PIT
  audit (Layer-1) has run at least once. Research workflows (notebooks,
  experiments) are permitted.
- **Entry requirement**: S0 exit + Layer-1 audit report with no unresolved
  red findings.
- **Exit to S2**: Layer-1 clean + Layer-2 mechanism-validity memo
  committed, featuring a proof-of-observability citation for every input.

### S2 — Validated model
- **What exists**: a locked model under the frozen-regime (`regime: A`)
  prereg; an outer walk-forward report; a CPCV challenger report; a
  calibration report. The Layer-3 forecast-validity criteria from
  `promotion_thresholds` are satisfied.
- **Entry requirement**: S1 exit + Layer-3 canonical + challenger packs
  + challenge stack (1)+(2).
- **No decision-level claim may be made at S2.** Layer-4 is not yet
  evaluated. The desk may not contribute to paper-live decisions from S2
  alone.

### S3 — Decision candidate
- **What exists**: Layer-4 net-of-cost evaluation under the two-scenario
  cost stress (optimistic + pessimistic). Pessimistic positive-expected-
  utility constraint is satisfied. Shadow-rule DSR/PBO within pre-
  registered ceilings.
- **Entry requirement**: S2 exit + Layer-4 report + challenge stack (1)+(2).
- **v1 retirement trigger**: the commit that promotes the first v2.0 desk
  from S2 to S3 deletes the v1 raw-sum controller, the v1 gate pack, and
  the v1 desks listed in the approved plan (§B8).

### S4 — Shadow live
- **What exists**: the paper-live loop runs daily EOD against live feeds,
  using the internal-simulator execution adapter. Layer-5 operational
  validity is measured in production: release-calendar drills, feed
  outages, replay-from-snapshot, degradation-ladder transitions.
- **Entry requirement**: S3 exit + Layer-5 drill plan pre-registered +
  challenge stack (1)+(2). No real capital.
- **Exit to S5**: Layer-5 evidence pack + 14-day time-separated self-
  review (mechanism 3) + reviewer-self verdict.

### S5 — Constrained production
- **Not in v2 scope**. Paper-trading terminal state is S4; any transition
  to S5 requires a spec revision and the full challenge stack (1)+(2)+
  (3)+(4). Reserved for a future real-capital phase.

### S6 — Scaled production
- **Not in v2 scope**.

---

## 4. Acceptance layers (user spec §8)

Each layer is a promotion gate. A layer is "passed" only when the
corresponding evidence is committed to the desk's promotion evidence pack
and its hash is present in `validation_runs`.

### Layer 1 — Data validity
- PIT reconstruction test (every feature, every decision tick in scope).
- Release-lag audit per source.
- Revision audit per source (count, magnitude, direction).
- Stale-data abstention drill (simulated outages).
- Schema + checksum coverage at 100%.
- **Artefact**: `v2/audit/pit_audit.py` report. Referenced in the desk
  prereg at `contract_refs.data_contract_hash` and in the training-window
  determination.

### Layer 2 — Mechanism validity
- Feature-to-mechanism mapping memo.
- Proof that the mechanism is observable from decision-time data.
- Proof that a simpler benchmark (e.g. price-autocorrelation + seasonality)
  does not explain the claimed effect.
- **Artefact**: `mechanism.md` committed under the desk directory.

### Layer 3 — Forecast validity
- Outer walk-forward under `regime: A`.
- Pinball + approx-CRPS + DM/HAC + interval coverage + stability.
- Beats baselines B0 (EWMA-Gaussian) and B1 (empirical).
- CPCV challenger with 5-day purge + ≥5-day embargo.
- Shadow-rule DSR/PBO diagnostic within pre-registered ceilings.
- **Artefacts**: `walk_forward_report.json`, `cpcv_report.json`,
  `calibration_report.json`, `shadow_rule_diagnostics.json`.

### Layer 4 — Decision validity
- Gross + net performance under optimistic and pessimistic cost scenarios.
- Turnover distribution.
- Abstain-period exposure decomposition.
- Degradation-ladder PnL attribution.
- Scenario stress (EIA holiday, CFTC outage, WTI feed stall).
- Desk contribution by regime slice.
- **Artefact**: `decision_validity_report.json`.

### Layer 5 — Operational validity
- Shadow-mode run ≥ N business days (N pre-registered).
- Live feed failure drills executed and logged.
- Deterministic replay from persisted snapshots confirmed byte-identical.
- Kill-switch + rollback drill.
- Alerting + incident logging wired.
- **Artefact**: `operational_validity_log.jsonl` (append-only).

### Layer 6 — Independent validation
- Challenge stack (1)+(2) minimum at every forward transition from S2.
- Challenge stack (1)+(2)+(3) at S4→S5.
- External paid review at S5 and on material changes.
- **Artefact**: `validation_runs` row + `challenge_findings` rows.

---

## 5. Transition matrix

| From → To | Layers required | Challenge stack |
|---|---|---|
| S0 → S1 | L1 clean | (1) |
| S1 → S2 | L1 clean, L2 memo, L3 canonical + challenger | (1) + (2) |
| S2 → S3 | L4 report under two-scenario cost stress | (1) + (2) |
| S3 → S4 | L5 drill plan + prereg | (1) + (2) |
| S4 → S5 | L5 evidence pack, review expiry OK | (1) + (2) + (3) |
| S5 → S6 | stability period pre-registered in S5→S5 re-approval | (1) + (2) + (3) + (4) |

Deviations from the table's "Layers required" column are typed deviation
objects recorded against the target `validation_run`.

---

## 6. Demotion rules

A desk is **unconditionally demoted** when any of the following occurs. No
challenge-stack review is required; demotion is a safety primitive.

| Trigger | Demotion target |
|---|---|
| Layer-1 audit fails on a re-run | S0 |
| Checksum mismatch on any required source | S1 |
| Calibration score below hard-gate floor for ≥ N consecutive ticks (N pre-registered) | S2 |
| Hard-fail state fires ≥ K times in a rolling window | S2 |
| Shadow-mode replay hash divergence | S3 |
| Cost-scenario pessimistic EU turns negative on rolling review | S3 |
| Prereg deviation with `resolution_status = disputed` | hold at current state; block further promotions until resolved |
| External reviewer issues a `reject` verdict at a required gate | S3 (or lower per reviewer specification) |

Demotions are logged as `validation_runs.final_verdict = demote_to_Sx` and
trigger an incident in the operational log.

---

## 7. Approval expiry

Every promotion verdict carries an explicit expiry:

| State | Default expiry | Re-approval requirement |
|---|---|---|
| S2 | 365 days | Re-run L3 under current contract + (1)+(2) |
| S3 | 180 days | Re-run L4 under current contract + (1)+(2) |
| S4 | 90 days | L5 re-evaluation + time-separated review |
| S5 | 90 days | Full (1)+(2)+(3)+(4) re-approval |

At expiry, the desk is automatically **held** at its current state (no
new forward promotions), and the synthesiser continues to include it with
an automatically applied quality penalty until re-approval or demotion.

Expiry is computed from the date of the `final_verdict = promote`
transition into that state, not from the last evidence refresh.

---

## 8. Typed deviation lifecycle

A deviation moves through a state machine:

```
opened → resolved        (evidence persisted, gate passes)
opened → accepted        (residual risk documented, gate passes with explicit risk note)
opened → deferred        (promotion blocked; further work required)
opened → disputed        (promotion blocked; adjudication required)
```

- `resolved` and `accepted` admit promotion.
- `deferred` and `disputed` block promotion into the target state.
- A `deferred` deviation auto-escalates to `disputed` after a pre-
  registered duration.

Every transition is written to `validation_runs.deviations` and stamped
with `role` + `ts`.

---

## 9. Per-state challenge minimums (summary table)

Repeats `governance_model.md §1.1` for convenience; the authoritative
source is that document.

| Target state | Mech (1) prereg | Mech (2) challenger | Mech (3) time-sep | Mech (4) external |
|---|---|---|---|---|
| S1 | required | — | — | — |
| S2 | required | required | — | — |
| S3 | required | required | — | — |
| S4 | required | required | — | — |
| S5 | required | required | required | required |
| S6 | required | required | required | required |
| new family | required | required | required | required |
| new model class | required | required | required | required |
| post-incident re-approval | required | required | required | required |

---

## 10. Example: oil v2.0 `prompt_balance_nowcast`

- S0 — concept memo: "EIA weekly balances nowcast 5-day WTI log return
  via a dynamic-factor state-space model over crude/gasoline/distillate
  stocks, refinery runs, imports, and calendar spreads."
- S1 — Layer-1 PIT audit passes over the ALFRED + EIA vintage corpus; the
  audit names the earliest defensibly-reconstructible `as_of_ts`, which
  becomes the training-window start.
- S2 — locked prereg; ROWF-CPCV run; Layer-3 beats B0+B1 on pinball and
  approx-CRPS with DM-HAC support; CPCV median path improvement; shadow-
  rule DSR within ceiling; challenge memo + rebuttal matrix closed.
- S3 — Layer-4 two-scenario cost stress shows positive pessimistic EU;
  v1 raw-sum controller deleted in the same commit.
- S4 — paper-live loop runs 60 business days with two scheduled release
  delays and one simulated WTI feed stall; degradation ladder transitions
  match expectation; replay hash invariant holds.
- v2.0 terminal state is S4. S5 requires a spec revision.

---

## 11. Forbidden

- Promoting past S2 without a committed `contract_hash` referencing the
  current `v2_decision_contract.md` hash in `docs/v2/hashes/`.
- Promoting to any state while any `disputed` or `deferred` deviation
  remains against the target `validation_run`.
- Promoting to S3 without deleting the v1 raw-sum controller.
- Using `sim_equity_vrp/` or any v1 simulator output as Layer-3, Layer-4,
  or Layer-5 evidence.
- Skipping the time-separated self-review on any S4→S5 or new-family
  promotion.
- Logging a demotion as a `promote` verdict, or vice versa.
