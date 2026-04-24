# Current project status

**Last updated**: 2026-04-24  
**Owner**: Henri Rapson  
**Source of truth rule**: this file is the live dashboard. Detailed evidence remains in the linked artefacts.

## 1. Current state

| Area | Status | Evidence / notes |
|---|---|---|
| v1 architecture | Phase 1 complete; Phase 2 MVP portability verified. | `../phase1_completion.md`, `../phase2_mvp_completion.md` |
| v1.16 restructure | Shipped and documented. | `master_plan.md`, `../first_principles_redesign.md`, `raid_log.md` D-15/D-18 |
| Reliability gate | 86-decision reliability sample assessed clean; full 4h wall-clock gate was deliberately interrupted and is not claimed passed. | `master_plan.md`, `raid_log.md` I-01, `reliability_sample_assessment_2026-04-24.md` |
| Capability debits | Remaining open debits are model-quality focused. | `../capability_debits.md` |
| v2 redesign | B6b-B10 accepted; Phase B complete; S4-0 executor implemented. S4-0 now accepts local/free or synthetic replay data; real/licensed data is no longer a phase requirement. | `../v2/b6b_paper_live_spec.md`, `../v2/b7_replay_snapshot_spec.md`, `../v2/b8_runtime_restore_spec.md`, `../v2/b9_killctl_spec.md`, `../v2/b10_phase_b_dry_run_spec.md`, `../v2/phase_b_closeout.md`, `../v2/s4_0_dry_run_plan.md`, `../v2/s4_0_execution_spec.md`, `../v2/s4_0f_free_data_rehearsal.md` |
| S4 test layer | First executable slice shipped: CL roll policy, synthetic replay quality, timestamp/lineage evidence, and market-depth claim limits. Formal S4 is no longer blocked on licensed CL data. | `../v2/s4_test_execution_status.md` |

## 2. Next outcomes

| Priority | Outcome | Target / trigger | Tracking |
|---|---|---|---|
| 1 | Treat the completed free-data replay as accepted S4-0 operating-model evidence, with source limitations recorded as non-claims. | Current phase closeout. | `../v2/s4_0f_free_data_rehearsal.md`, generated `manifest.yaml` |
| 2 | Execute the updated local/free S4-0 runner contract and then expand to one week if clean. | Before any broader S4 claim. | `../v2/s4_0_execution_spec.md`, `../v2/s4_0_run_config_template.yaml` |
| 3 | Decide whether the clean 86-decision sample is enough for current PM purposes or whether exact 4h evidence is still needed. | Before making a strict §12.2 reliability-gate claim. | `raid_log.md` I-01, `reliability_sample_assessment_2026-04-24.md` |

## 3. Open exceptions

| ID | Exception | Type | Next action |
|---|---|---|---|
| I-01 | 4h Reliability gate not completed; 86-decision sample assessed clean after deliberate interrupt. | Issue | Treat as partial reliability evidence unless/until exact 4h gate evidence is required. |
| I-02 | Real/licensed CL front/next data unavailable. | Closed issue | Requirement removed by scope decision; S4-0 proceeds on local/free or synthetic replay evidence. |
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
| 2026-04-24 | S4-0 external research memo | See `../v2/s4_0_research_findings.md`, `../v2/s4_0_licence_clearance_checklist.md` | Archived commercial-data research; no longer a hard gate |
| 2026-04-24 | `uv run pytest tests/v2/s4_0 -q` | 3 passed | S4-0 recorded replay executor fixture acceptance |
| 2026-04-24 | `uv run ruff check v2/s4_0 v2/governance/s4_0.py tests/v2/s4_0` | All checks passed | S4-0 executor touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 238 passed | No v2 regression after S4-0 executor |
| 2026-04-24 | `uv run pytest tests/v2/s4_0 -q` | 5 passed | S4-0F stage-label support acceptance |
| 2026-04-24 | `uv run ruff check v2/s4_0 v2/governance/s4_0.py tests/v2/s4_0` | All checks passed | S4-0F touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 240 passed | No v2 regression after S4-0F support |
| 2026-04-24 | `uv run python -m v2.governance.s4_0 --config data/s4_0/free_source_wti_futures/s4_0f.yaml --overwrite` | Green; 20 decisions, 40 simulated ledger rows, replay and restore passed | S4-0F free-data operational rehearsal |
| 2026-04-24 | `uv run pytest tests/test_soak_checkpoint.py tests/test_soak_monitor.py tests/test_soak_incident.py tests/test_soak_runner_short.py -q` | 25 passed | Soak runner focused regression coverage |
| 2026-04-24 | Reliability sample run, interrupted by operator direction | 5,104s elapsed; 86 decisions; 430 forecasts; 86 resource samples; 0 soak incidents; FDs 5 to 5; final RSS 38.89 MB | Partial reliability-gate sample assessment |
| 2026-04-24 | `uv run pytest tests/v2/s4_0 -q` | 19 passed | S4 test-layer execution: roll, replay-quality, market-depth limits, lineage |
| 2026-04-24 | `uv run ruff check v2/s4_0 tests/v2/s4_0` | All checks passed | S4 touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 254 passed | No v2 regression after S4 test-layer execution |
| 2026-04-24 | `uv run pytest tests/v2/s4_0 -q` | 20 passed | S4 local/free replay scope: no licensed-data gate |
| 2026-04-24 | `uv run ruff check v2/s4_0 tests/v2/s4_0` | All checks passed | S4 local/free replay touched-code lint |
| 2026-04-24 | `uv run pytest tests/v2 -q` | 255 passed | No v2 regression after removing licensed-data requirement |

## 5. This-week commitment

Keep this to at most three outcomes.

- [x] Commission S4-0 data-source and licence research.
- [x] Execute S4-0F free-data operational rehearsal on existing WTI futures data.
- [x] Reconcile reliability-gate status with an 86-decision partial sample assessment.
