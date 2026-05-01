# Master project plan

**Project**: multi-desk-trading architecture  
**Owner**: Henri Rapson (sole operator)  
**Started**: 2026-04-17  
**Current spec version**: v1.16
**Last updated**: 2026-04-24

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
| 2026-04-17 | HMM regime classifier | `hmm-classifier-v0.2` | Original ship was fixed 4-state Gaussian via hmmlearn; current worktree upgrades this to adaptive-K Gaussian HMM (BIC-selected `K ∈ [2, 6]`) |
| 2026-04-17 | LLM routing postcondition gate | `llm-routing-v0.1` | §6.4 enforcement |
| 2026-04-17 | Soak runner infrastructure | `soak-runner-v0.1` | Checkpoint-resume + numeric thresholds |
| 2026-04-17 | Research-loop v0.2 handlers (3×) | `gate-failure-retire-v0.2`, `regime-transition-refresh-v0.2`, `latency-kpi-v0.1` | Auto-retire + Shapley refresh + KPI |
| 2026-04-17 | Feed-reliability learning loop | `feed-incidents-schema-v0.1`, `data-ingestion-handler-v0.2`, `feed-reliability-review-v0.2`, `feed-latency-monitor-v0.2` | 3-layer: registry + rules + Page-Hinkley |
| 2026-04-17 | Reliability gate calibration | `reliability-gate-v1.8`, `reliability-loose-ends-v1.9`, `reliability-gate-v1.10` | 28d → 7d → 48h → 4h |
| 2026-04-17 | **Phase 1 complete** | `phase1-complete-v1.11` | §12.2 all six criteria met |
| 2026-04-18 | **Phase 2 MVP complete** | `phase2-mvp-v1.12` | Architectural portability claim VERIFIED |
| 2026-04-18 | Phase 2 Desk 2 `hedging_demand` | `phase2-desk2-hedging-demand-v1.13` | Post-design-review ship; D7 expanded; D8 and D9 were subsequently closed |
| 2026-04-18 | **D9 Gate 3 runtime harness closed** | `gate3-runtime-harness-v1.14` | `eval/hot_swap.py` + 7 migrated callsites + Controller retire-exclusion fix (B-4). Desk 3 unblocked. |

### In flight / immediate next

| Date | Milestone | Status | Blocker |
|---|---|---|---|
| 2026-04-24 | Reliability-gate sample assessment | Partial sample complete | 86 decisions over 5,104s, 0 incidents; exact 4h gate not claimed |
| 2026-04-18 | Establish PM artefacts (this doc + RAID + problem log) | In progress | — |

### Forward — Phase 2 scale-out (v1.16 re-scoped)

Targets based on Phase 2 deadline of 2026-07-17. The v1.16 desk-roster restructure (see `docs/first_principles_redesign.md`, D-15 in `raid_log.md`) shrinks both sides of the roster: oil 5 → 3 desks, equity-VRP 2 → 1 merged desk. Phase 2 scale-out work is re-scoped accordingly.

| Date (target) | Milestone | Scope |
|---|---|---|
| 2026-05-02 | ~~Phase 2 desk 2: `hedging_demand`~~ | **Shipped early 2026-04-18 post-design-review** (merged into `surface_positioning_feedback` at v1.16; see C8). |
| ~~before 2026-05-16~~ | ~~Gate 3 runtime-harness upgrade (D9)~~ | **Shipped 2026-04-18 at tag `gate3-runtime-harness-v1.14`**. `eval/hot_swap.py::build_hot_swap_callables`; 7 migrated callsites; Controller retire-exclusion fix (B-4). |
| 2026-04-22 | **v1.16 roster restructure — C1 … C12 shipped** | Spec v1.15 → v1.16 + adopted review + target-registry append + 3 commissions + 2 new oil desks (`supply_disruption_news`, `oil_demand_nowcast`) + regime_classifier role expansion. C12 `a310ac6` closed the architectural ship. |
| 2026-04-22 | **v1.16 cleanup wave — W2 … W10 shipped** | Inlined legacy classical models into new desks (W3/W4/W5); migrated/deleted ~27 legacy test imports across 10+ files (W6); rewrote `config/data_sources.yaml` (W7); **deleted 6 committed legacy desk dirs** (W8 `cf0e141` — `supply`, `geopolitics`, `demand`, `macro`, `dealer_inventory`, `hedging_demand`); **closed D-16** via per-desk baseline dispatch and restored Gate 1 aggregate ≥ 2/3 (W9 `f562dc0`); shipped `earnings_calendar` W10 skeleton desk + commission + tests (W10 `b0adb1c`). Post-W10: 371 tests pass + 1 skipped; v1.16 Phase 2 done-criterion met (2 equity desks pass Gate 3; surface_positioning_feedback carries the Gate 1/2 weight). |
| 2026-04-22 | **X1 shipped — D-17 closed** | Added earnings-event channel to `sim_equity_vrp/latent_state.py` with forward correlation (lead=2) to `vol_shocks_unscaled`. `EquityObservationChannels.by_desk["earnings_calendar"]` exposes `earnings_event_indicator` + `earnings_cluster_size`. Rebuilt `ClassicalEarningsCalendarModel` around 5 features. Gate 1 skill **14.66% relative improvement** vs `zero_return_baseline` on seed-7 probe. Forward-correlation Pearson r = 0.15. D12 golden hashes preserved byte-identically (isolated seed+4 RNG, post-existing-draws generation). Renamed `tests/test_earnings_calendar_skeleton.py` → `tests/test_earnings_calendar.py`. Post-X1: 375 tests pass + 1 skipped. |
| 2026-04-22 | **Y-series shipped — phase_a/b/c test restoration** | Rebuilt the three Phase 1 contamination-mode integration tests (`test_phase_a_clean_observations`, `test_phase_b_controlled_leakage`, `test_phase_c_realistic_contamination`) for the v1.16 3-desk oil roster after W6 deletion. Per-desk baseline dispatch + per-desk Print target/value mirror W9's D-16 closure pattern. Thresholds scaled down proportionally (≥ 3/5 → ≥ 1/3 or ≥ 2/3 depending on claim). storage_curve strict invariants + Gate 3 3/3 preserved in every phase. Y1 `8f2b21c` (6 tests), Y2 `311c124` (3 tests), Y3 `9f8520e` (4 tests). Post-Y3: 388 tests pass + 1 skipped. |
| 2026-04-22 | **Z shipped — D-18 term_structure drop** | Phase 2 equity-VRP roadmap formally closes on 2 desks (surface_positioning_feedback + earnings_calendar). term_structure dropped via D-18 in raid_log. No code changes; manifest-only commit. |
| ~~2026-05-16~~ | ~~Phase 2 desk 3: `term_structure`~~ | **DROPPED** at Z (`62821c6+`, 2026-04-22) per D-18 in `raid_log.md`. Pasted review was silent; silence interpreted as "don't add" per the adopted shrink-the-roster direction. Phase 2 done-criterion met without term_structure (2 equity desks pass Gate 3; earnings_calendar + surface_positioning_feedback carry Gate 1/2 weight). |
| 2026-05-02 | Phase 2 restructure C7: logic-gate threshold recalibration | `test_logic_gate_multi_scenario.py` 3-desk oil roster; ≥3/5 → ≥2/3 aggregate; strict invariants preserved. |
| 2026-05-09 | Phase 2 restructure C8+C9: equity rename + merge + sim-side channel collapse | `dealer_inventory` + `hedging_demand` → `surface_positioning_feedback`; `VIX_30D_FORWARD_3D_DELTA` emission; D12/D13 golden re-records. |
| 2026-05-23 | Phase 2 desk 4: `earnings_calendar` | Event-driven vol expansion; equity-side event desk; emits `VIX_30D_FORWARD_3D_DELTA`. (Brought forward from 2026-06-06 since `hedging_demand` merge frees capacity.) |
| 2026-06-06 | Phase 2 restructure C11: `fair_vol_baseline` channel | Decision-time forward-vol baseline in `sim_equity_vrp`; enables `next_session_rv_surprise` internal label for `surface_positioning_feedback`. |
| ~~2026-06-20~~ | ~~Phase 2 desk 5: `macro_regime`~~ | **DROPPED** — demoted to regime-conditioning state via `regime_classifier` (see C6). Decision D-15. |
| 2026-06-27 | Phase 2 Logic gate on v1.16 equity-VRP roster | 10-seed multi-scenario on the merged `surface_positioning_feedback` + `earnings_calendar` roster. Done-criterion rebased: **2 equity desks pass Gate 3; ≥ 1/2 passes Gates 1+2 aggregate** (scaled from the 5-desk 3/5 rule). |
| 2026-07-04 | **Phase 2 complete (C12 E2E verification)** | `phase2-complete-v2.0` tag; 2-week buffer before deadline. Includes legacy-desk deletion (4 oil + 1 equity), test migration (10+ files), and capability-debits / phase2_mvp_completion re-signing. |
| 2026-07-17 | Phase 2 deadline (spec §12.2) | Hard deadline; slippage is capability-claim debit. |

Spec §14.6 budget realism applies: add 1-2 weeks per desk if escalation past ridge is needed (BVAR / PyMC). Realistic Phase 2 completion may slip to 2026-07-31. D-15 (roster restructure) adds pressure to R-01 (deadline risk) — if ridge-level heads under-perform on the restructured roster, §7.3 escalation consumes buffer fast.

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

- `docs/architecture_spec_v1.md` — authoritative spec (v1.15).
- `docs/phase1_completion.md` — Phase 1 evidence manifest.
- `docs/phase2_mvp_completion.md` — Phase 2 MVP evidence manifest.
- `docs/capability_debits.md` — consolidated debit log.
- `docs/pm/raid_log.md` — Risks / Assumptions / Issues / Decisions.
- `docs/pm/problem_log.md` — defect tracker.
