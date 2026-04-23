# v2 kill-switch and rollback

**Status**: D4 paper artefact. Read-only.
**Tag**: `v2-killswitch-0.1`
**Scope**: every v2 running loop — paper-live, backtest, shadow replay.

---

## 1. What this document is

Defines the **abort conditions**, **rollback primitives**, **degraded-mode
thresholds**, and **replay-from-snapshot procedure** for v2. These are the
operational-safety layer. They sit beneath the decision contract's
degradation ladder (which handles ABSTAIN and TTL expiry) and above the
promotion lifecycle's demotion rules (which move a desk backwards in the
state machine).

The progression from least to most disruptive:

```
degradation ladder  →   kill-switch     →   demotion      →   v1 rollback
(decision contract)     (this document)     (lifecycle)       (this document)
```

---

## 2. Scope ladder

A kill-switch activation operates at one of three scopes:

| Scope | Effect | Who/what triggers |
|---|---|---|
| **Desk** | Named desk abstains indefinitely; its forecasts are excluded from family synthesis; position contribution decays per λ. | Automated triggers (§4) or operator command. |
| **Family** | All desks in a family hard-fail simultaneously; family emits ABSTAIN; positions force-flat over a pre-registered decay window. | Automated triggers (§4) or operator command. |
| **System** | All v2 families hard-fail; paper-live loop halts; execution adapter flattens the book; a dated incident record is opened. | Operator command only. No automated system-level kill. |

Scope is always **recorded explicitly** in the incident log, including the
minimal scope that the evidence supports. Over-scoping a kill-switch is
itself an incident.

---

## 3. Kill-switch artefacts

Three on-disk artefacts drive kill-switch behaviour:

### 3.1 `v2/runtime/kill_switch.yaml`

```yaml
system_state: enabled | frozen | halted
families:
  oil_wti_5d:
    state: enabled | desk_isolated | frozen | halted
    isolated_desks: []
    reason: ""
    triggered_by: operator | automated_rule_id
    triggered_at: 2026-05-04T18:11:00Z
    expires_at: null | timestamp
    incident_ref: null | incident_id
```

The paper-live loop **reads this file at every decision tick** before
requesting desk forecasts. Any state other than `enabled` short-circuits
the family / desk's forecast request and records an ABSTAIN with a
`abstain_reason = "kill_switch:<reason>"` on the family decision.

### 3.2 `v2/runtime/incidents.jsonl`

Append-only. One JSON line per incident:

```json
{
  "incident_id": "inc_2026-05-04_001",
  "opened_at": "2026-05-04T18:11:00Z",
  "scope": "family|desk|system",
  "scope_ref": "oil_wti_5d" | "oil_wti_5d/prompt_balance_nowcast" | "system",
  "severity": "sev1|sev2|sev3",
  "trigger": "automated_rule_id | operator",
  "reason": "free text",
  "evidence_refs": ["..."],
  "expected_resolution_by": "timestamp",
  "closed_at": null,
  "closure_evidence_refs": [],
  "post_incident_review_required": true
}
```

### 3.3 `v2/runtime/snapshots/`

One directory per snapshot:

```
snapshots/
    2026-05-04T16-30-00Z/
        family_decisions.parquet
        desk_forecasts.parquet
        positions.parquet
        execution_ledger.parquet
        pit_manifest_snapshot.parquet
        git_head.txt            # commit SHA of v2 code + docs at snapshot time
        kill_switch.yaml        # snapshot copy
        snapshot.sha256         # signature over all files above
```

Snapshots are taken automatically after every successful paper-live EOD
tick and retained for a pre-registered window (default: 90 days).

---

## 4. Automated abort conditions

A rule fires at any of the following. Each rule declares its scope. The
rules are evaluated before every decision tick and also on every incoming
ingest write.

| Rule id | Condition | Scope | Action |
|---|---|---|---|
| `KS-D01` | `data_quality_score = 0` on any required source for a desk | desk | desk_isolated |
| `KS-D02` | checksum mismatch on any required source | desk | desk_isolated + sev2 incident |
| `KS-D03` | replay hash divergence on snapshot re-verification | desk | desk_isolated + sev1 incident |
| `KS-M01` | calibration_score < `c_min` for ≥ `N_cal` consecutive ticks | desk | desk_isolated |
| `KS-M02` | predictive dispersion > `σ̂_max` for ≥ `N_sigma` ticks | desk | desk_isolated |
| `KS-M03` | quantile monotonicity violation emitted by desk | desk | desk_isolated + sev2 incident |
| `KS-F01` | ≥ 2 desks in a family simultaneously desk_isolated | family | frozen |
| `KS-F02` | family synthesiser disagreement beyond bound for ≥ `N_syn` ticks | family | frozen |
| `KS-O01` | release-calendar version mismatch between prereg and runtime | family | frozen + sev2 incident |
| `KS-O02` | DuckDB manifest corruption | family | frozen + sev1 incident |
| `KS-O03` | pit_manifest checksum verification failure at startup | family | frozen + sev1 incident |

Constants (`c_min`, `N_cal`, `σ̂_max`, `N_sigma`, `N_syn`) are declared in
the family prereg and the model inventory (pending D5). A rule fire is
idempotent: re-firing on the same cause does not reopen the incident.

---

## 5. Operator commands

Three operator commands (CLI under `v2/governance/killctl.py`, reserved
for Phase B):

```
killctl isolate  <family>/<desk>   --reason "<text>" --evidence <path>
killctl freeze   <family>          --reason "<text>" --evidence <path>
killctl halt     --reason "<text>" --evidence <path>
killctl clear    <family>[/<desk>] --resolution-evidence <path> --incident <id>
```

- Every command opens or closes an incident and writes to
  `v2/runtime/kill_switch.yaml` + `v2/runtime/incidents.jsonl`.
- `clear` requires a closed incident with `closure_evidence_refs` populated
  and, where the closed incident was `sev1` or `sev2`, a post-incident
  review memo committed to the desk directory.
- The CLI **refuses** to clear a family while any of its desks remain
  `desk_isolated`.

---

## 6. Rollback primitives

Three rollback primitives are defined. They escalate in disruption.

### 6.1 Hot-swap to a previously promoted desk version

The hot-swap contract — re-pointed from v1 and re-homed as
`v2/governance/rollback.py` — permits atomic swap of a desk implementation
to a previously promoted version within the same family synthesiser, at a
pre-agreed boundary (next EOD tick).

- **Scope**: desk only.
- **Pre-requisite**: the target version must have a prior
  `final_verdict = promote` in `validation_runs` at state ≥ S2 with
  unexpired approval.
- **Effect**: synthesiser switches over at the next tick; all subsequent
  `family_decisions` rows cite the swapped desk version.
- **Not an incident by itself** but must be logged with a rationale.

### 6.2 Replay-from-snapshot

Full loop-state restore from `v2/runtime/snapshots/<ts>/`:

- System is halted (`killctl halt`).
- Positions are reconciled against the snapshot's `positions.parquet`.
- `pit_manifest_snapshot.parquet` is diffed against the live manifest;
  any vintage that arrived after the snapshot is either (a) replayed in
  order against the restored state, or (b) deferred to a post-restore
  catch-up, per the operator command.
- Execution adapter ledger is rewound; subsequent fills are re-simulated
  under the code at `git_head.txt`.
- `snapshot.sha256` verified before replay begins; any mismatch aborts
  restore and escalates to a sev1 incident.

### 6.3 v1 rollback (this is an explicit, separate primitive)

Return the repo to pre-v2 behaviour:

```
git switch wip-attribution-and-desk-models
rm -rf v2/
```

- v1 code has been preserved on its own branch. The v2 branch never
  deletes from the v1 branch; the two are discrete histories sharing a
  common ancestor at `d0d3a14`.
- **Scope**: system. Entirely disables v2.
- **Use case**: emergency-only, for catastrophic contract / data / code
  defects discovered before a desk has reached S3. After v1 deletion (at
  the S2→S3 commit for the first v2.0 desk), this primitive reduces to a
  `git revert` of that deletion commit and is classified as sev1 by default.

---

## 7. Degraded-mode thresholds (interaction with the decision contract)

The decision contract defines the degradation ladder within a valid
operational state. The kill-switch operates **above** that ladder: when a
kill-switch rule fires, it **overrides** the ladder.

```
kill_switch.state != enabled   →   family/desk ABSTAIN with kill_switch reason
kill_switch.state == enabled   →   degradation ladder applies per contract
```

This ordering must be enforced in the paper-live loop: kill-switch is
consulted **first**, degradation ladder **second**. A desk may not escape
a kill-switch activation by emitting a valid forecast.

---

## 8. Incident severity

| Severity | Trigger class | Review requirement |
|---|---|---|
| sev1 | System-level halt; replay-hash divergence; manifest corruption; rollback invocation | Mandatory post-incident review within 14 days; external paid review required before returning to S4+ |
| sev2 | Family freeze; checksum mismatch; quantile monotonicity violation; release-calendar version mismatch | Mandatory post-incident review within 14 days |
| sev3 | Desk isolation from data-quality or calibration rules | Review recommended; not mandatory |

A post-incident review memo is committed under
`docs/v2/incidents/<incident_id>.md` and linked from
`incidents.jsonl.closure_evidence_refs`.

---

## 9. Test discipline (mirroring the data contract's risk acceptance)

Kill-switch behaviour is covered by a **mandatory test pack** that runs in
CI:

- Every `KS-*` rule has at least one fault-injection test.
- Replay-from-snapshot is exercised end-to-end at least weekly via a
  scheduled CI job.
- Every operator command has at least one CLI test asserting incident-
  log writes and state-file updates.

A change to `v2/runtime/kill_switch.yaml` at CI time without a triggering
rule or operator command is a test failure.

---

## 10. Forbidden

- A kill-switch activation without an incident record.
- Clearing a kill-switch while any `disputed` or `deferred` deviation
  remains open on a desk in scope.
- Deleting a snapshot before its retention window expires.
- Using `sim_equity_vrp/` or any v1 fault-injection harness as the sole
  Layer-5 evidence for kill-switch behaviour.
- Hot-swapping to a desk version whose `final_verdict` is `demote_to_Sx`
  or whose approval has expired.
- Operator `halt` without committing an incident and a rollback-plan memo
  within 1 business day.
