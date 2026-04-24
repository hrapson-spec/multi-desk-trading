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

## Substrate

`substrate/` holds the phase-2 review artefacts that led to the v2 redesign.
They are historical input, not v2 specification.
