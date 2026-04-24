# Current project status

**Last updated**: 2026-04-24  
**Owner**: Henri Rapson  
**Source of truth rule**: this file is the live dashboard. Detailed evidence remains in the linked artefacts.

## 1. Current state

| Area | Status | Evidence / notes |
|---|---|---|
| v1 architecture | Phase 1 complete; Phase 2 MVP portability verified. | `../phase1_completion.md`, `../phase2_mvp_completion.md` |
| v1.16 restructure | Shipped and documented. | `master_plan.md`, `../first_principles_redesign.md`, `raid_log.md` D-15/D-18 |
| Reliability gate | 4h wall-clock soak still appears open in PM tracking. | `master_plan.md` in-flight row; `raid_log.md` I-01 |
| Capability debits | Remaining open debits are model-quality focused. | `../capability_debits.md` |
| v2 redesign | B6b-B10 accepted; Phase B complete; S4-0 recorded replay planning baseline created. | `../v2/b6b_paper_live_spec.md`, `../v2/b7_replay_snapshot_spec.md`, `../v2/b8_runtime_restore_spec.md`, `../v2/b9_killctl_spec.md`, `../v2/b10_phase_b_dry_run_spec.md`, `../v2/phase_b_closeout.md`, `../v2/s4_0_dry_run_plan.md` |

## 2. Next outcomes

| Priority | Outcome | Target / trigger | Tracking |
|---|---|---|---|
| 1 | Commission S4-0 data-source and licence research. | Before S4-0 run execution. | `../v2/s4_0_researcher_brief.md` |
| 2 | Select S4-0 recorded replay source or record blocker. | After external research. | `../v2/s4_0_dry_run_plan.md`, `../v2/s4_0_evidence_manifest.md` |
| 3 | Resolve the 4h reliability soak status for the older v1 track. | Before any v1 phase-complete claim that depends on it. | `raid_log.md` I-01 |

## 3. Open exceptions

| ID | Exception | Type | Next action |
|---|---|---|---|
| I-01 | 4h Reliability gate soak not yet executed / not yet reconciled. | Issue | Run it, attach evidence, or explicitly accept as debit. |
| I-02 | S4-0 data source and licence not yet selected. | Issue | Commission research; no S4-0 execution claim until licence, entitlement, storage, replay, and reviewer-access rights are clear. |
| R-03 | Single-operator bus factor. | Risk | Keep current-status and manifests clean enough for handover. |
| A-08 | Git tags and commit messages are the audit trail. | Assumption | Confirm whether v2 hash/signing discipline supersedes this. |

## 4. Latest useful verification

Record only verification that supports a project claim.

| Date | Command / evidence | Result | Claim supported |
|---|---|---|---|
| 2026-04-22 | Phase 2 manifest evidence | See `../phase2_mvp_completion.md` | v1.16 restructure and MVP portability status |
| 2026-04-24 | `uv run pytest tests/v2/execution tests/v2/paper_live -q` | 46 passed | B6b execution + paper-live acceptance |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 216 passed | No v2 regression after B6b |
| 2026-04-24 | `uv run ruff check v2/desks/base.py v2/execution/__init__.py v2/execution/simulator.py v2/paper_live v2/runtime tests/v2/execution/test_simulator.py tests/v2/paper_live` | All checks passed | B6b touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q` | 51 passed | B7 replay verification + adjacent runtime/paper-live acceptance |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 221 passed | No v2 regression after B7 |
| 2026-04-24 | `uv run ruff check v2/runtime v2/execution/simulator.py tests/v2/runtime` | All checks passed | B7 touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q` | 55 passed | B8 restore tooling + adjacent runtime/paper-live acceptance |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 225 passed | No v2 regression after B8 |
| 2026-04-24 | `uv run ruff check v2/runtime tests/v2/runtime` | All checks passed | B8 touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q` | 62 passed | B9 killctl + adjacent runtime/paper-live acceptance |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 232 passed | No v2 regression after B9 |
| 2026-04-24 | `uv run ruff check v2/runtime v2/governance tests/v2/runtime` | All checks passed | B9 touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q` | 65 passed | B10 dry-run + composed runtime substrate acceptance |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 235 passed | No v2 regression after B10 / Phase B closeout |
| 2026-04-24 | `uv run ruff check v2/runtime v2/governance tests/v2/runtime` | All checks passed | B10 touched-code lint |
| 2026-04-24 | S4-0 planning artefacts | See `../v2/s4_0_dry_run_plan.md`, `../v2/s4_0_researcher_brief.md`, `../v2/s4_0_evidence_manifest.md`, `../v2/s4_0_report_template.md` | S4-0 recorded replay plan baseline |

## 5. This-week commitment

Keep this to at most three outcomes.

- [ ] Commission S4-0 data-source and licence research.
- [ ] Select S4-0 recorded replay source or record blocker.
- [ ] Reconcile reliability-gate status.
