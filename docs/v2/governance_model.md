# v2 governance model

**Status**: D2 paper artefact. Read-only.
**Tag**: `v2-governance-0.1`
**Scope**: every promotion cycle in v2.
**Companion artefact**: `prereg_template.yaml` (canonical pre-registration schema).

---

## 1. What this document is

This model operationalises "independent challenge" for a **solo operator**.
SR 11-7 and the NIST AI RMF both assume a separate validation function;
v2's terminal state is paper-trading with one person at the controls. The
governance model below substitutes for organisational separation with a
**four-part challenge stack**, state-gated so that cost scales with promotion
material.

### 1.1 The stack

1. **Pre-registration protocol** — ex ante lock.
2. **Challenger-agent adversarial review** — structured red-team attack.
3. **Time-separated self-review** — fresh-eyes reproduction.
4. **External paid review** — real independent validation at material gates.

| State transition | Minimum mandatory mechanisms |
|---|---|
| State 0 → 1 | (1) only |
| State 1 → 2 | (1) + (2) |
| State 2 → 3 | (1) + (2) |
| State 3 → 4 | (1) + (2) |
| State 4 → 5 | (1) + (2) + (3) |
| State 5 → 6 | (1) + (2) + (3) + (4) |
| New decision family | (1) + (2) + (3) + (4) |
| New model class | (1) + (2) + (3) + (4) |
| Post-incident re-approval | (1) + (2) + (3) + (4) |

---

## 2. Mechanism (1): Pre-registration

### 2.1 Artefact

A `promotion_prereg.yaml` per desk per promotion cycle. Schema: see
`prereg_template.yaml` in this directory.

### 2.2 Discipline

- Committed to `v2/desks/<family>/<desk>/preregs/<YYYY-MM-DD>-<slug>.yaml`
  **before** the outer walk-forward is run.
- Commit-SHA and file-SHA256 captured at commit time and persisted to
  `validation_runs.prereg_hash`.
- An annotated git tag (format `prereg-<family>-<desk>-<YYYY-MM-DD>`) marks
  the prereg commit.
- **Signing escalation**: v2.0 uses annotated tags + file-SHA256 as the
  binding receipt. GPG-signed tags (`git tag -s`) are required before any
  State 5 promotion. This escalation is a typed deviation from the default
  state-gated stack and is recorded in `model_inventory.md`.

### 2.3 Enforcement

- `v2/governance/prereg.py` provides a `check_run` function that diffs the
  realised run (features actually read, model hyperparameters actually
  fitted, outer-protocol parameters actually used) against the prereg.
- Any non-whitelisted deviation is a typed `deviation` object persisted to
  `validation_runs.deviations` and blocks promotion until resolved.

### 2.4 Whitelisted deviations

Only the deviation classes enumerated in the prereg's `allowed_deviations`
section are admissible without re-registration. Typical examples:
  - data-vendor outage with logged operational exception;
  - federal-holiday release-calendar shift (auto-detected);
  - non-material scraper version bump (hash-diff within pre-declared patch
    envelope).

Anything else is a protocol failure.

---

## 3. Mechanism (2): Challenger-agent adversarial review

### 3.1 Role separation

The challenger-agent runs as a **distinct session** with `--role challenger`.
It receives the frozen evidence pack and the prereg; it does **not** receive
the author's commentary, the debit ledger, or any resolution discussion. Its
mandate is explicitly adversarial: identify reasons promotion should not
proceed.

### 3.2 Inputs (fixed)

- `promotion_prereg.yaml` + its SHA-256.
- Layer-1 PIT audit report.
- Layer-3 outer walk-forward report (ROWF).
- Layer-3 CPCV challenger report.
- Layer-3 calibration report.
- Layer-4 cost-stress report (optimistic + pessimistic).
- Shadow-rule DSR/PBO pack (Layer-3 challenger diagnostics).
- Full deviation register for the run.

### 3.3 Output (fixed schema)

`challenge_memo.md` with mandatory sections:

1. Look-ahead / vintage impurity
2. Selection leakage
3. Re-used holdout / tuning contamination
4. Feature eligibility timing
5. Overlap / embargo correctness
6. Benchmark weakness
7. Overfitting signs
8. Calibration failure modes
9. Degradation / abstention behaviour
10. Why deployment should not proceed

Plus a structured verdict block:

```yaml
challenge_verdict:
  promote: false
  blockers:
    - id: CH-01
      title: "short description"
      severity: blocker
      category: leakage | calibration | selection | vintage | overlap | benchmark | overfit | degradation | other
      evidence_ref: "evidence pack path or metric reference"
      suggested_test: "what would falsify this concern"
  warnings:
    - id: CH-02
      ...
  notes:
    - ...
```

### 3.4 Rebuttal matrix

The author responds with a `rebuttal_matrix.md`:

| Finding ID | Status | Resolution evidence | Residual risk |
|---|---|---|---|
| CH-01 | resolved / accepted / deferred / disputed | pointer to evidence | description |

Promotion is blocked while any `blocker` carries status `disputed` or
`deferred`. `accepted` blockers must be discharged with either evidence or
a typed contract deviation.

---

## 4. Mechanism (3): Time-separated self-review

### 4.1 Cooling-off periods

| Trigger | Minimum wait |
|---|---|
| Routine desk re-promotion | 14 calendar days |
| First desk in a new family | 28 calendar days |
| New model class | 28 calendar days |
| Post-incident re-approval | 14 calendar days (plus external review) |

### 4.2 Protocol

1. Author freezes the evidence pack + prereg + challenger memo + rebuttal
   matrix at `T_freeze`.
2. No work on this desk is permitted during the cooling-off period.
3. At `T_freeze + Δ`, re-enter with `--role reviewer_self`. The CLI enforces
   that no session state from the original author session is restored.
4. Reviewer-self independently re-executes:
   - feature build,
   - forecast generation,
   - scoring pack,
   - challenger replay,
   - promotion verdict.
5. Reviewer-self writes a signed verdict block.

### 4.3 Acceptance rule

```
promote iff
    author_verdict == "promote"
  AND reviewer_self_verdict == "promote"
  AND reproduced_metrics within pre-registered tolerance
  AND pipeline hashes match (data path + code path)
```

Divergence fails the promotion automatically and triggers a root-cause
investigation that is itself a typed `validation_run`.

---

## 5. Mechanism (4): External paid review

### 5.1 Trigger gates

- First transition to State 5 (constrained production).
- First promotion of any new decision family.
- First use of any materially new model class.
- Any overlay / override that materially changes outputs.
- Post-incident re-approval after a Severity-1 failure.

### 5.2 Package delivered to reviewer

- Prereg + SHA-256.
- Data dictionary + per-source release calendar.
- PIT reconstruction proof.
- Feature eligibility proofs per source.
- Outer walk-forward report.
- CPCV report.
- Shadow-rule DSR/PBO pack.
- Challenge memo + rebuttal matrix.
- Known-limitations register (from automated capability-debit ledger).
- Proposed promotion decision record.

### 5.3 Deliverable

A written validation memo with fixed sections:

1. Conceptual soundness
2. Data and vintage integrity
3. Implementation verification
4. Outcome analysis
5. Limitations and overlays
6. Independent promotion verdict

### 5.4 Budget

External review is the only mechanism in this document that carries a
per-invocation £-cost. It triggers a per-feed-style business-case memo
justifying the reviewer's scope and fee against the material change that
triggered the review.

---

## 6. CLI role enforcement

`v2/governance/validate.py` is the single entry point for promotion
activity:

```
validate run --role author         --desk <family>/<desk> --prereg <path>
validate run --role challenger     --desk <family>/<desk> --evidence-pack <path>
validate run --role reviewer_self  --desk <family>/<desk> --freeze-id <uuid>
validate run --role external       --desk <family>/<desk> --reviewer <name>
```

The CLI:

- refuses to start a reviewer-self session within the cooling-off window;
- refuses to write to any artefact owned by another role;
- stamps every write with `role`, `ts`, and `operator_fingerprint`;
- refuses to issue a final promotion verdict unless all mechanisms required
  by the target state transition have produced admissible verdicts.

---

## 7. Persistence schema

Two DuckDB tables live under `v2/governance/persistence.py`:

```sql
CREATE TABLE validation_runs (
    validation_run_id     TEXT PRIMARY KEY,
    family                TEXT NOT NULL,
    desk                  TEXT NOT NULL,
    target_state          TEXT NOT NULL,       -- S0..S6
    prereg_path           TEXT NOT NULL,
    prereg_hash           TEXT NOT NULL,
    evidence_pack_path    TEXT NOT NULL,
    evidence_pack_hash    TEXT NOT NULL,
    author_verdict        TEXT,                -- promote | reject | defer
    challenger_verdict    TEXT,
    reviewer_self_verdict TEXT,
    external_verdict      TEXT,
    blocker_count         INTEGER NOT NULL DEFAULT 0,
    warning_count         INTEGER NOT NULL DEFAULT 0,
    deviations            JSON NOT NULL DEFAULT '[]',
    final_verdict         TEXT,
    created_at            TIMESTAMP NOT NULL,
    closed_at             TIMESTAMP
);

CREATE TABLE challenge_findings (
    finding_id            TEXT PRIMARY KEY,
    validation_run_id     TEXT NOT NULL REFERENCES validation_runs,
    source                TEXT NOT NULL,       -- prereg | challenger | reviewer_self | external
    severity              TEXT NOT NULL,       -- blocker | warning | note
    category              TEXT NOT NULL,       -- leakage | calibration | selection | vintage | overlap | benchmark | overfit | degradation | other
    finding_text          TEXT NOT NULL,
    evidence_ref          TEXT,
    resolution_status     TEXT,                -- open | resolved | accepted | disputed | deferred
    resolution_evidence_hash TEXT,
    created_at            TIMESTAMP NOT NULL,
    resolved_at           TIMESTAMP
);
```

---

## 8. Deviation objects

Any departure from prereg, contract, or this governance model is a typed
`deviation` object:

```yaml
- id: DEV-03
  type: allowed_data_outage_exception | unapproved_feature_swap | model_hyperparameter_drift | ...
  opened_at: 2026-05-04T18:22:11Z
  opened_by_role: author
  related_validation_run_id: vr_9e2a...
  rationale: "EIA release delayed by federal holiday; used prior-week vintage"
  approved_by_role: reviewer_self | null
  approved_at: null | timestamp
  affected_decision_ids: [...]
```

Un-typed deviations are prohibited. The prereg loader rejects deviations
whose `type` is not enumerated in `v2/governance/deviation_types.yaml`.

---

## 9. What this model does not replace

- It does not replace real external validation at State 5 — mechanism (4)
  is mandatory there.
- It does not replace the Layer-1 PIT audit — that is a data-validity gate
  upstream of this governance stack.
- It does not replace the promotion lifecycle itself — see `D3 —
  promotion_lifecycle.md` (pending) for the state machine.

---

## 10. Forbidden

- Running `validate run --role challenger` in the same session as
  `--role author` without a CLI-enforced session boundary.
- Writing to `validation_runs.final_verdict` without all required role
  verdicts present.
- Using the automated capability-debit ledger as a substitute for the
  challenger-agent memo — the ledger feeds the challenger; it does not
  replace it.
- Promoting past State 4 without a time-separated self-review, regardless
  of author confidence.
- Escalating a `disputed` blocker to `resolved` without corresponding
  evidence persisted at `challenge_findings.resolution_evidence_hash`.
