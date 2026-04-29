# Phase 3 Candidate Audits — Complete

Created: 2026-04-29
Scope: WTI 3-day return-sign audit candidates over free public post-2020 PIT
families

## Context

The corrected 3-day all-calendar feasibility count is **N=310** after
purge/embargo, which clears the Phase 3 floor for the raw event calendar.
That is only a tractability result. Each strategy candidate must still clear
the residual-mode Phase 3 thresholds:

- directional accuracy gain vs `zero_return_baseline` >= 5.00 pp
- Newey-West HAC effective N on residuals >= 250
- block-bootstrap effective N on residuals >= 250

## Audit Matrix

| Candidate | Family / data scope | N after purge | Scored residuals | Accuracy gain | HAC N | Bootstrap N | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| FOMC event dummy + WTI lag | WPSR + FOMC + OPEC support calendar | 285 | 239 | n/a | 224 | 236 | NON-ADMISSIBLE |
| WPSR inventory surprise | WPSR value-bearing PIT panel | 272 | 227 | +6.61 pp | 176 | 175 | NON-ADMISSIBLE |
| OPEC ministerial content flags | Curated OPEC calendar labels | 47 | 36 | -8.33 pp | 27 | 36 | NON-ADMISSIBLE |
| GPR shock week | GPR weekly calendar + current public daily snapshot values | 291 | 221 | -1.81 pp | 164 | 168 | NON-ADMISSIBLE |
| PSM calendar pulse | EIA PSM/EIA-914 calendar only | 75 | 63 | +12.70 pp | 58 | 63 | NON-ADMISSIBLE |
| STEO calendar pulse | EIA STEO calendar only | 76 | 64 | +9.38 pp | 47 | 50 | NON-ADMISSIBLE |
| WTI strict lag | 1d all-calendar pivot | 648 | 589 | +5.09 pp | 524 | 547 | ADMISSIBLE_PROVISIONAL |

## Interpretation

No 3d audited candidate clears Phase 3. The common failure mode is residual
effective N, not merely headline event count.

The two monthly calendar-pulse candidates (PSM and STEO) show positive nominal
accuracy gain versus the zero-return baseline, but they are not admissible:
monthly cadence leaves far too few scored residuals, and the current ingesters
do not parse production or forecast table values. These are triage results,
not evidence that EIA-914 or STEO value surprises have been tested.

The GPR audit has a stricter data caveat: PIT contains the weekly event
calendar, while the GPR value panel was taken from the current public snapshot
for this audit. It is useful as a falsification run, but a promotion candidate
would need true PIT vintages or a defensible release-lag rule for the value
series.

The first numerical success appears only after pivoting to the 1d horizon:
the all-calendar strict previous-trading-day WTI lag candidate clears all
numeric Phase 3 gates. It is provisional because it was discovered after the
3d candidate set failed; promotion requires a forward lock and rerun.

## Files

New candidate packages:

- `feasibility/candidates/wpsr_inventory_3d/`
- `feasibility/candidates/opec_ministerial_3d/`
- `feasibility/candidates/gpr_shock_3d/`
- `feasibility/candidates/psm_calendar_3d/`
- `feasibility/candidates/steo_calendar_3d/`
- `feasibility/candidates/wti_lag_1d/`

New audit scripts:

- `feasibility/scripts/audit_wpsr_inventory_3d_phase3.py`
- `feasibility/scripts/audit_opec_ministerial_3d_phase3.py`
- `feasibility/scripts/audit_gpr_shock_3d_phase3.py`
- `feasibility/scripts/audit_psm_calendar_3d_phase3.py`
- `feasibility/scripts/audit_steo_calendar_3d_phase3.py`
- `feasibility/scripts/audit_wti_lag_1d_phase3.py`

New reports:

- `feasibility/reports/terminal_2026-04-29_phase3_audit_wpsr_inventory.md`
- `feasibility/reports/terminal_2026-04-29_phase3_audit_opec_ministerial.md`
- `feasibility/reports/terminal_2026-04-29_phase3_audit_gpr_shock.md`
- `feasibility/reports/terminal_2026-04-29_phase3_audit_psm_calendar.md`
- `feasibility/reports/terminal_2026-04-29_phase3_audit_steo_calendar.md`
- `feasibility/reports/terminal_2026-04-29_phase3_audit_wti_lag_1d.md`

## Next Decision

The current free-public, 3d candidate set is exhausted. The next productive
branch is not another 3d calendar-pulse audit; it is one of:

1. Forward-lock the 1d WTI lag candidate and score future events unchanged.
2. Build value-bearing v1.1 parser for PSM/EIA-914 tables, then
   pre-register production-surprise state candidates.
3. Retry Stooq CL/Brent/RBOB/NG ingestion once an operator-provided Stooq API
   key is available, then move to multi-asset target
   tractability with per-target N accounting.
4. Stop the 3d strategy class at Phase 3 and preserve the negative results as
   capability debits.

## Verification

- `.venv/bin/pytest tests/ -q`: **917 passed, 1 skipped, 15 warnings**
- `.venv/bin/ruff check .`: clean
- `.venv/bin/ruff format --check` on all touched feasibility candidate,
  audit-script, and test files: clean
