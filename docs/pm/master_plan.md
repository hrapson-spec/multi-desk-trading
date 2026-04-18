# Master project plan

**Project**: multi-desk-trading architecture  
**Owner**: Henri Rapson (sole operator)  
**Started**: 2026-04-17  
**Current spec version**: v1.13  
**Last updated**: 2026-04-18

## 1. Purpose

Build a multi-desk, agent-led coordination architecture for systematic trading research. The deliverable is the **architecture** — contracts, orchestration, research loop, attribution — not a P&L number. Success is measured by redeployment to an unrelated asset class (equity VRP — the Speckle and Spot project) with zero shared-infrastructure changes.

Full authoritative statement in `docs/architecture_spec_v1.md` §1.

## 2. Phase structure

Three phases with discrete gates. Spec §12 is authoritative; this section is the operational tracker.

| Phase | Target | Done-criterion | Deadline |
|---|---|---|---|
| Phase 1 | Build the architecture on crude-oil domain | §12.2 six done-criteria | 2026-04-17 ✓ |
| Phase 2 MVP | Prove zero-change portability via one equity-VRP desk | `phase2_mvp_completion.md` | 2026-04-18 ✓ |
| Phase 2 scale-out | Four more equity-VRP desks + richer market | 5 desks pass Gate 3; 3/5 pass Gates 1+2 aggregate | 2026-07-17 |
| Phase 3 | Live event-scoring loop validation | Not yet scoped in spec | TBD post-Phase 2 |

## 3. Timeline — actual + forward-looking

### Completed

| Date | Milestone | Tag | Notes |
|---|---|---|---|
| 2026-04-17 | Project start; spec v1.0 freeze | `spec-v1.0` | First commit: architecture spec + skeleton |
| 2026-04-17 | Week-0 scaffold complete | `scaffold-v1.0` | DuckDB schema, bus, contracts, persistence |
| 2026-04-17 | Six stub desks | `stubs-v1.0` | Hot-swap passes, skill fails by construction |
| 2026-04-17 | Controller v1.0 | `controller-v1.0` | Regime-conditional linear sizing + §14.8 cold-start |
| 2026-04-17 | Three hard gates + attribution | `gates-v1.0`, `lodo-v0.1`, `shapley-v0.1` | LODO + Shapley co-primary |
| 2026-04-17 | Storage-curve classical specialist | `storage-curve-classical-v0.1` | Load-bearing desk |
| 2026-04-17 | Phases A+B+C simulator + 5 desks | `phases-abc-v0.1` | Clean → leakage → realistic contamination |
| 2026-04-17 | HMM regime classifier | `hmm-classifier-v0.2` | 4-state Gaussian via hmmlearn |
| 2026-04-17 | LLM routing postcondition gate | `llm-routing-v0.1` | §6.4 enforcement |
| 2026-04-17 | Soak runner infrastructure | `soak-runner-v0.1` | Checkpoint-resume + numeric thresholds |
| 2026-04-17 | Research-loop v0.2 handlers (3×) | `gate-failure-retire-v0.2`, `regime-transition-refresh-v0.2`, `latency-kpi-v0.1` | Auto-retire + Shapley refresh + KPI |
| 2026-04-17 | Feed-reliability learning loop | `feed-incidents-schema-v0.1`, `data-ingestion-handler-v0.2`, `feed-reliability-review-v0.2`, `feed-latency-monitor-v0.2` | 3-layer: registry + rules + Page-Hinkley |
| 2026-04-17 | Reliability gate calibration | `reliability-gate-v1.8`, `reliability-loose-ends-v1.9`, `reliability-gate-v1.10` | 28d → 7d → 48h → 4h |
| 2026-04-17 | **Phase 1 complete** | `phase1-complete-v1.11` | §12.2 all six criteria met |
| 2026-04-18 | **Phase 2 MVP complete** | `phase2-mvp-v1.12` | Architectural portability claim VERIFIED |
| 2026-04-18 | Phase 2 Desk 2 `hedging_demand` | `phase2-desk2-hedging-demand-v1.13` | Post-design-review ship; D7 expanded, D8+D9 opened |

### In flight / immediate next

| Date | Milestone | Status | Blocker |
|---|---|---|---|
| 2026-04-18 → ~04-25 | Run 4h Reliability gate soak | Pending (operator-side) | Requires 4 hours of laptop uptime |
| 2026-04-18 | Establish PM artefacts (this doc + RAID + problem log) | In progress | — |

### Forward — Phase 2 scale-out

Targets based on Phase 2 deadline of 2026-07-17 (three months from Phase 1 exit). Each scale-out desk mirrors the `dealer_inventory` MVP pattern.

| Date (target) | Milestone | Scope |
|---|---|---|
| 2026-05-02 | ~~Phase 2 desk 2: `hedging_demand`~~ | **Shipped early 2026-04-18 post-design-review** |
| before 2026-05-16 | Gate 3 runtime-harness upgrade (D9) | Replace `lambda: True` stubs with a seeded Controller.decide() run; apply retroactively to dealer_inventory + hedging_demand. MUST ship before Desk 3. |
| 2026-05-16 | Phase 2 desk 3: `term_structure` | Implied-realized term spread; mirror of oil `demand` desk |
| 2026-06-06 | Phase 2 desk 4: `earnings_calendar` | Event-driven vol expansion; mirror of oil `geopolitics` |
| 2026-06-20 | Phase 2 desk 5: `macro_regime` | Equity vol-regime (quiet/stress/recovery) desk; mirror of oil `macro` |
| 2026-06-27 | Phase 2 Logic gate on equity-VRP | 10-seed multi-scenario parallel to oil Logic gate |
| 2026-07-04 | **Phase 2 complete** | `phase2-complete-v2.0` tag; 2-week buffer before deadline |
| 2026-07-17 | Phase 2 deadline (spec §12.2) | Hard deadline; slippage is capability-claim debit |

Spec §14.6 budget realism applies: add 1-2 weeks per desk if escalation past ridge is needed (BVAR / PyMC). Realistic Phase 2 completion may slip to 2026-07-31.

### Forward — Phase 3 (not yet scoped)

Per spec §1.2, the validation terminus is "paper backtest + live event-scoring loop on post-pretraining-cutoff data." Phase 3 would:

- Wire real-data feeds for oil (EIA WPSR, CFTC COT, OPEC MOMR, JODI — free sources only per §1.2).
- Run the live event-scoring loop for ≥ N months (N TBD).
- Report realised vs. predicted performance.
- First attempt at Phase 2 equity-VRP redeployment on real Speckle-and-Spot data.

**Phase 3 is not yet scoped in the spec.** Adding it is a v2.x spec revision item. Target start: after Phase 2 complete (~2026-07-04).

## 4. Dependencies (external)

- **Speckle and Spot project**: needs to have identifiable equity-VRP desk analogues (currently met via synthetic MVP; real-data follow-on depends on that project's state).
- **Free data feeds**: EIA, CFTC, OPEC, JODI, Caldara-Iacoviello GPR, OFAC/HMT/EU sanctions, Google Trends. All synthetic-only until Phase 3.
- **Compute**: 8GB M-series Mac for inference. Fine-tuning (if needed) requires borrowed compute (Colab / cloud).

## 5. Deliverables register

Every phase produces a completion manifest. `docs/phase1_completion.md` and `docs/phase2_mvp_completion.md` already exist.

Future:
- `docs/phase2_completion.md` (at Phase 2 scale-out ship)
- `docs/phase3_completion.md` (TBD)

## 6. Communication cadence

Solo operator — no meetings. PM artefacts update on major milestones (tag a new spec version, ship a phase). This master plan is updated whenever a milestone ships or a new dependency / risk emerges.

## 7. What "done" looks like, project-wide

**Success**: spec v2.0 with all three phases green + manifests + real live-event-scoring performance numbers. The architectural capability claim is verified end-to-end.

**Partial success (capability debit)**: Phase 2 ships but 2-3 desks fail Gate 1/2 on the real market; logged as debits; architecture claim still stands.

**Failure modes (abandon triggers per §12.3)**:
1. ≥ 2 desks fail sign-preservation on real data.
2. Research-loop latency > 2 weeks on event-driven triggers.
3. Scaffolding exceeded 6 weeks (N/A — scaffold was 1 day).
4. contracts/v1.py needs a v2 bump before Phase 2 runs (N/A — MVP shipped with v1.x).

## 8. Related artefacts

- `docs/architecture_spec_v1.md` — authoritative spec (v1.12).
- `docs/phase1_completion.md` — Phase 1 evidence manifest.
- `docs/phase2_mvp_completion.md` — Phase 2 MVP evidence manifest.
- `docs/capability_debits.md` — consolidated debit log.
- `docs/pm/raid_log.md` — Risks / Assumptions / Issues / Decisions.
- `docs/pm/problem_log.md` — defect tracker.
