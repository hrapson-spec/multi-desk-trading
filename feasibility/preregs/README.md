# Feasibility Pre-Registrations

Pre-registrations under `feasibility/preregs/` are **v1 feasibility audit
documentation**. They are NOT v2 promotion pre-registrations.

## What lives here

A pre-registration committed under this directory pins a **feasibility
audit candidate**: a model that runs through the v1 tractability harness
(`feasibility/tractability_v1.py`) to produce a Phase 3 audit verdict.
The candidate stays under `feasibility/candidates/<slug>/` and **does
not** register as a `desks/` desk — it does not participate in
`Controller.decide` (`controller/decision.py:94`). The audit's purpose
is to test whether a candidate can clear the spec v1 §13 dependence
analysis on actual model residuals (not just raw target).

## How this differs from v2 promotion pre-registrations

The v2 governance model (`docs/v2/governance_model.md` §6, line 49)
expects promotion pre-registrations under
`v2/desks/<family>/<desk>/preregs/<YYYY-MM-DD>-<slug>.yaml`. Those
preregs:

- Bind a **v2 desk** that emits `ForecastV2` on the bus
- Cite v2 contract hashes (`v2/contracts/decision_unit.py`,
  `v2/pit_store/manifest.py`, etc.)
- Are validated by `v2/governance/prereg.py:check_run` against the
  v2 target registry at `v2/contracts/target_variables.py`
- Are tagged `prereg-<family>-<desk>-<YYYY-MM-DD>` at lock time

A feasibility pre-registration here:

- Binds an **audit-only candidate** under `feasibility/candidates/`
- Cites the v1 target registry at `contracts/target_variables.py`
  (which already includes 3d variants per the data plan)
- Is validated by harness invocation, not by the v2 governance check
- Does NOT modify `v2/contracts/target_variables.py`
- Is NOT a stepping stone to v2 promotion in this directory; promotion
  is a separate operator-driven cycle that would copy the prereg into
  `v2/desks/<family>/<desk>/preregs/...`, add the v2 target spec, and
  pass the v2 governance check

## Filename convention

`<YYYY-MM-DD>-<slug>.yaml`. The date is the prereg authoring date.
The slug is the audit candidate's identifier (e.g. `fomc_wti_3d`).

## Schema

The schema mirrors `docs/v2/prereg_template.yaml` for consistency, but
with two distinguishing markers at the top:

```yaml
prereg_version: "feasibility-v1.0"   # NOT "2.0.0"
feasibility_audit_only: true         # custom field signalling non-promotion
```

Any prereg here must include `forbidden_after_lock` containing
`register_as_v2_desk_without_promotion_review` to make the boundary
explicit.

## Lifecycle

1. **Author**: commit the prereg under this directory before fitting
   the candidate model.
2. **Audit run**: `feasibility/scripts/audit_<slug>.py` invokes the
   harness in `--phase3-residual-mode` with the candidate's residuals.
3. **Verdict**: written to
   `feasibility/reports/terminal_<date>_phase3_audit_<slug>.md`.
4. **If audit clears Phase 3**: operator may (separately) initiate a
   v2 promotion cycle. That cycle authors a parallel v2 prereg under
   `v2/desks/<family>/<desk>/preregs/`, adds the v2 target spec, and
   runs the v2 governance check. **No automatic promotion.**
5. **If audit fails**: documented as a negative-result deliverable per
   CLAUDE.md §1.3.4.
