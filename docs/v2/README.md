# v2 redesign

This directory holds the read-only paper artefacts (Phase D) of the v2 redesign
plus implementation specifications for Phase B build slices.
No `v2/` Python code may land on this branch until `D5 — Inventory + ownership` is
tagged and signed. See the approved plan at
`~/.claude/plans/see-the-multi-desk-trading-humble-mist.md` for the full
ten-round brainstorm and the six-layer promotion lifecycle this directory
operationalises.

## What v2 is

v2 reframes the repo as a **point-in-time decision engine for market hypotheses**,
not a "multi-desk trading system". The four separable layers are:

1. **Data truth** — bitemporal PIT feature store with release-calendar semantics.
2. **Mechanism models** — desks that are identifiable from real observables.
3. **Decision synthesis** — canonical-unit forecasts combined into a
   family-level distribution and a target risk budget.
4. **Execution + post-trade control** — simulated paper-live adapter with
   explicit degradation ladder and kill-switch.

A six-layer promotion standard (data / mechanism / forecast / decision /
operational / independent validation) applies to the whole chain, not just to
the forecasting code.

## What v2 is not

- Not a successor to v1's "domain-portable architecture" objective. v2 is
  judged on **real decision quality under real PIT data**, not on portability.
- Not dependent on `sim_equity_vrp/` or any other v1 simulator as promotion
  evidence. The v1 simulator is re-classified to a software / contract /
  fault-injection testbed with **zero promotion authority**.
- Not a real-capital system. Terminal state is paper-trading against live
  feeds. Governance is enforced as practice.

## Design decisions

Locked decisions from the 10-round brainstorm are tabulated in the approved
plan at `~/.claude/plans/see-the-multi-desk-trading-humble-mist.md`. Any
deviation from that table during Phase D or Phase B requires an explicit
deviation record per `D3 — promotion_lifecycle.md` (once tagged).

## Phase D commit spine

| Tag | Artefacts |
|---|---|
| `v2-contracts-0.1` | `v2_decision_contract.md`, `v2_data_contract.md` |
| `v2-governance-0.1` | `governance_model.md`, `prereg_template.yaml` |
| `v2-lifecycle-0.1` | `promotion_lifecycle.md` |
| `v2-killswitch-0.1` | `kill_switch_and_rollback.md` |
| `v2-inventory-0.1` | `model_inventory.md`, `ownership_rules.md` |

Each tag is signed. Each artefact carries its own SHA-256 hash which is
persisted into the `promotion_prereg.yaml` for any desk that cites it.

## Phase B implementation specs

| Slice | Artefact | Purpose |
|---|---|---|
| B6b | `b6b_paper_live_spec.md` | Stateful internal simulator + paper-live loop after B6a execution primitives. |
| B7 | `b7_replay_snapshot_spec.md` | Replay/snapshot receipt verification before S4-style operational claims. |
| B8 | `b8_runtime_restore_spec.md` | Restore verified runtime state into a fresh runtime root. |
| B9 | `b9_killctl_spec.md` | Operator kill-switch commands and incident log path. |
| B10 | `b10_phase_b_dry_run_spec.md` | Deterministic Phase B operational dry-run closeout. |

## S4 recorded replay planning

| Artefact | Purpose |
|---|---|
| `s4_0_dry_run_plan.md` | Pre-run plan for the first no-capital recorded replay rehearsal. |
| `s4_0_researcher_brief.md` | Archived external research commission for optional commercial data sources. |
| `s4_0_research_findings.md` | Archived external research output; Databento is no longer a gate. |
| `s4_0_licence_clearance_checklist.md` | Archived checklist; no longer a requirement for S4-0 local/free replay execution. |
| `s4_0_execution_spec.md` | Executable recorded-replay runner boundary, command, and acceptance tests. |
| `s4_0f_free_data_rehearsal.md` | Free-data operational rehearsal result now accepted under the local/free S4-0 scope. |
| `s4_0_closeout.md` | Formal S4-0 closeout decision under the revised local/free scope. |
| `s4_1_synthetic_tick_book_spec.md` | Next gate for synthetic tick and order-book fixture validation. |
| `s4_1_closeout.md` | Formal S4-1 closeout decision. |
| `s4_2_mbp10_simulated_fill_spec.md` | MBP-10 simulated-fill drill specification. |
| `s4_2_mbp10_simulated_fill_results.md` | MBP-10 simulated-fill drill metric results. |
| `s4_2a_synthetic_claim_diagnostics.md` | Synthetic queue-position, hidden-liquidity, and profitability diagnostics. |
| `s4_2b_replay_microstructure_integration.md` | Integration of microstructure diagnostics into recorded-replay evidence packs. |
| `s4_3_wti_model_quality_diagnostic.md` | Local/free WTI walk-forward model-quality diagnostic and baseline result. |
| `s4_test_execution_status.md` | Executed test-layer status for CL roll policy, synthetic tick replay semantics, lineage, and market-depth claim limits. |
| `s4_0_run_config_template.yaml` | Local run-config template for local/free or synthetic replay files. |
| `s4_0_evidence_manifest.md` | Required evidence pack structure for reviewer-grade S4-0 assessment. |
| `s4_0_report_template.md` | Post-run report template using pre-registered stop/go criteria. |

## Substrate

`substrate/` holds the phase-2 review artefacts that led to the v2 redesign.
They are historical input, not v2 specification.
