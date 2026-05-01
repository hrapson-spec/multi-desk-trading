# v2 ownership rules

**Status**: D5 paper artefact. Read-only.
**Tag**: `v2-inventory-0.1`
**Scope**: the disciplines a solo operator must follow to operate the
four-part challenge stack credibly.

---

## 1. Roles

Every v2 governance action is performed in one of four roles:

| Role | Responsibility | Fires in |
|---|---|---|
| `author` | Builds the desk, writes prereg, runs walk-forward + CPCV, collects evidence, proposes promotion. | S0–S4 forward motion. |
| `challenger` | Red-teams the frozen evidence pack against the prereg. Produces `challenge_memo.md`. Never co-author. | Every forward transition from S1. |
| `reviewer_self` | Re-executes the pipeline after a cooling-off window. Produces an independent promotion verdict. | S4→S5 and material promotions. |
| `external` | Paid reviewer. Produces a validation memo. | S5, new family, new model class, material overlay, post-incident. |

---

## 2. Role-mode discipline

The operator holds every role at v2.0. That is acceptable **if and only
if** the role boundaries are defended in three ways:

1. **Separate CLI session.** Every `validate run --role <r>` executes in
   a fresh shell with no inherited environment variables, no reused
   Python process, and no access to the author's notebook history.
2. **Session-boundary refusal.** The CLI rejects an attempt to run two
   roles in the same session; it records `role` and `session_id` on
   every write.
3. **Typed artefacts only.** Each role writes to its own artefact set
   (prereg / evidence pack / challenge memo / rebuttal matrix / self-
   review verdict). Cross-writes are rejected.

---

## 3. Cooling-off windows

| Trigger | Minimum wait | Enforcement |
|---|---|---|
| Routine desk re-promotion | 14 calendar days | CLI refuses `--role reviewer_self` start before expiry. |
| First desk in a new family | 28 calendar days | CLI refuses; override requires external reviewer. |
| New model class | 28 calendar days | CLI refuses; override requires external reviewer. |
| Post-incident re-approval | 14 calendar days + external | CLI refuses until external memo committed. |

During the cooling-off window the desk's directory is **read-only** from
the operator's shell. Enforcement is via a shell hook installed by
`v2/governance/validate.py` on CLI entry.

---

## 4. External-review triggers

External review is mandatory for:

- First transition to S5 (constrained production) — not in v2 scope.
- First promotion of any new decision family.
- First use of any materially new model class.
- Any overlay or manual intervention that materially changes a committed
  decision.
- Post-incident re-approval after any sev1 failure.

The operator may not promote past S4 without an external verdict for any
of the triggers above.

---

## 5. Operator fingerprint

Every governance write records:

- ISO-8601 UTC timestamp.
- Role.
- Session UUID.
- SSH or GPG key fingerprint (operator's public key; optional at v2.0,
  mandatory pre-S5).

Fingerprints are loaded from `~/.config/v2/operator.yaml`; the file path
is declared in `model_inventory.md §5` for each reviewer role.

---

## 6. Shadow-mode etiquette

While a desk is in S4 shadow-live:

- The operator may run backtests against new candidate versions in a
  separate workspace, but must not write to the live paper-live loop's
  `pit_root`.
- Prereg edits for the shadow-live desk are prohibited; a new prereg
  for a candidate version is permitted.
- Kill-switch interactions from the author role are prohibited except in
  response to a sev1 incident. Routine desk isolation at v2.0 is the
  reviewer_self role's responsibility.

---

## 7. Incident discipline

Opening an incident is a governance action; closing one is also a
governance action. The operator may open an incident in any role. Closing
requires:

- `author` role for routine `sev3` incidents (e.g. data-quality desk
  isolation).
- `reviewer_self` for `sev2` incidents.
- `external` verdict required before closing any `sev1` incident and
  before resuming S4+ operation.

---

## 8. Commit discipline

Every commit that:

- promotes a desk,
- demotes a desk,
- changes monitoring thresholds,
- clears a kill-switch, or
- closes an incident,

must:

1. Update `model_inventory.md` in the same commit.
2. Reference the `validation_run_id` in the commit body.
3. Include the updated `docs/v2/hashes/` receipt for any artefact whose
   content changed.

Commits that violate these rules are rejected at CI (pending Phase B).

---

## 9. What solo operation does not grant

- It does not grant exemption from external review at the triggers in §4.
- It does not grant shorter cooling-off windows than §3.
- It does not grant the ability to combine the `author` and `challenger`
  roles in a single session.
- It does not grant informal deviation handling; every deviation is a
  typed object per `docs/v2/promotion_lifecycle.md §8`.

---

## 10. Forbidden

- Changing role in the middle of an open `validation_run`.
- Back-dating any role's timestamp.
- Using a reviewer_self verdict produced without a true freeze of the
  evidence pack at the author's closing checkpoint.
- Opening an incident without a structured reason field that cites at
  least one `KS-*` rule id or an operator-command invocation.
- Editing `model_inventory.md` in a commit that changes no code, evidence,
  or prereg (prevents drift-by-memory in a solo setting).
