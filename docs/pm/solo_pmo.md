# Solo PMO operating model

**Owner**: Henri Rapson  
**Created**: 2026-04-24  
**Purpose**: provide just enough project-control discipline to keep the work visible, auditable, and moving without turning a solo research project into bureaucracy.

## 1. Operating principles

1. **One live dashboard.** `docs/pm/current_status.md` is the first page to read and the last page to update at the end of a work session.
2. **Evidence beats memory.** A milestone is only complete when the evidence path, test result, tag, or manifest is recorded.
3. **Manage by exception.** Normal variation stays in the work session. Anything that breaches a tolerance goes into RAID or the problem log.
4. **Products before activity.** Track deliverables, gates, and evidence; do not track effort for its own sake.
5. **Small cadence, hard gates.** Use a light weekly review, but keep phase gates strict.
6. **No hidden debt.** Accepted limitations belong in `docs/capability_debits.md`; defects belong in `docs/pm/problem_log.md`; strategic risks and decisions belong in `docs/pm/raid_log.md`.

## 2. PMO artefacts

| Artefact | Role | Update trigger |
|---|---|---|
| `current_status.md` | Live dashboard: phase, next milestone, open exceptions, immediate work. | End of every meaningful work session; always before stopping for more than a day. |
| `master_plan.md` | Roadmap baseline and stage history. | Milestone shipped, scope baseline changes, phase gate changes. |
| `raid_log.md` | Risks, assumptions, issues, decisions. | New strategic uncertainty, material decision, or tolerance breach. |
| `problem_log.md` | Bugs, regressions, resolved defects. | Any failed test, latent bug, or production-like incident. |
| `../capability_debits.md` | Accepted capability limitations. | Any known gap that does not block the current phase but weakens a claim. |
| Completion manifests | Phase-exit evidence packs. | At every phase or major gate close. |
| Engineering commissions | Work-package briefs for bounded build slices. | Before implementation; close or supersede after shipment. |

## 3. Weekly control loop

Run this once per week, or before any major context switch.

1. **Dashboard refresh**: update `current_status.md`.
2. **Milestone check**: confirm the next target, due date, and evidence required.
3. **RAID review**: close stale items, update triggers, add one clear next action for each open high/medium item.
4. **Debt review**: confirm open debits are still in-budget and tied to mitigation.
5. **Quality check**: record the latest meaningful test result if it supports a milestone claim.
6. **Next-week commitment**: choose at most three outcomes, not tasks.

## 4. Exception tolerances

Use these thresholds to decide whether something must be logged or escalated.

| Dimension | Tolerance | If breached |
|---|---|---|
| Schedule | Next milestone forecast slips by more than 7 calendar days. | Add/update RAID risk or issue; update `master_plan.md`. |
| Scope | A new deliverable changes a phase exit criterion or adds a new model/desk family. | Add RAID decision; update baseline plan. |
| Quality | A gate weakens, a test is deleted without replacement, or evidence becomes indirect. | Add problem or capability debit. |
| Architecture | Shared-infra changes are needed for a portability claim. | Stop and record decision before continuing. |
| Governance | A promotion, demotion, or phase claim lacks evidence. | Do not mark complete; add issue. |
| Operational | Reliability soak, replay, or paper-live run finds a resource, data, or determinism failure. | Add problem log entry and RAID issue if strategically material. |

## 5. Decision rules

Use the smallest record that preserves the audit trail.

- **Decision goes in `raid_log.md`** when it changes roadmap, scope, gate criteria, architecture, or accepted risk.
- **Problem goes in `problem_log.md`** when the code, tests, or process did something wrong and was or must be fixed.
- **Debit goes in `capability_debits.md`** when the project proceeds with a known limitation.
- **Manifest gets updated** when a claim is made externally: phase complete, gate complete, portability verified, v2 paper artefact complete.

## 6. Work-package template

Use this for any new commission or material implementation slice.

```markdown
## Work package: <name>

**Owner**: Henri  
**Status**: proposed | active | blocked | shipped | superseded  
**Target date**: YYYY-MM-DD  
**Decision / RAID link**: D-xx / R-xx / I-xx  

### Outcome
What must be true when this is done.

### Scope
Files, modules, or documents in scope.

### Out of scope
Explicit exclusions.

### Acceptance evidence
- Test:
- Manifest:
- Tag / commit:
- Review:

### Stop / escalate if
- Condition that invalidates the plan.
```

## 7. Session close checklist

Before ending a substantial session:

- [ ] Tests or verification result recorded if it supports a claim.
- [ ] `current_status.md` reflects the real next action.
- [ ] Any new risk, issue, decision, problem, or debit is logged in the right place.
- [ ] Any shipped work package has evidence and is not still marked "not yet implemented".
- [ ] No stale future milestone remains in `master_plan.md` as if it is still planned.

## 8. Monthly hygiene

Once per month:

1. Remove stale roadmap rows or mark them historical.
2. Check document headers for stale `Last updated` dates.
3. Reconcile README status against `current_status.md`.
4. Check all open high/medium RAID items have next actions.
5. Confirm v1/v2 governance boundary is explicit.
