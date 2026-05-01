# External Expert Commission: WPSR 1d Forward-Edge Candidate

Use this as a standalone prompt for an external research engineer, quantitative
researcher, or agentic code-review/implementation expert.

---

You are being commissioned to solve one specific problem in this GitHub branch:

`https://github.com/hrapson-spec/multi-desk-trading/tree/feasibility-harness-v0`

Start from these two files:

1. Full technical handoff:
   `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/docs/operations/wpsr_1d_candidate_handoff.md`
2. This commission brief:
   `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/docs/operations/wpsr_1d_external_expert_commission.md`

If you clone locally, use:

```bash
git clone https://github.com/hrapson-spec/multi-desk-trading.git
cd multi-desk-trading
git checkout feasibility-harness-v0
```

The repo contains a feasibility harness and an automated forward-evidence loop
for a provisional WTI trading-system candidate. The system is not trading
capital. The current bottleneck is not infrastructure; it is whether we can
produce a clean, causal, forward-promotable signal that beats simple baselines.

## The Problem To Solve

Determine whether a value-bearing WPSR candidate can produce a credible edge for:

`wti_front_1d_return_sign`

The candidate should use WPSR inventory/supply information available at or before
the WPSR decision timestamp and must be evaluated without leakage.

The narrow research question is:

> Can WPSR release-time inventory/supply information predict the next 1-day WTI
> return sign well enough to beat both the zero-return baseline and the
> realized majority-sign baseline under the repository's locked feasibility
> protocol?

This is intentionally narrow. We are not asking for a broad alpha search, a new
framework, or an execution system.

## Desired Outcome

The ideal outcome is a new, audit-only WPSR 1d candidate that:

- Is point-in-time safe.
- Is pre-registered before result inspection.
- Produces walk-forward residuals.
- Runs through the repository's residual-mode Phase 3 harness.
- Beats the zero-return baseline.
- Beats the majority-sign baseline, preferably by at least `+2.0 pp`.
- Clears the residual effective-N gates:
  - HAC effective N >= `250`
  - block-bootstrap effective N >= `250`
- Preserves the existing live forward lock.
- Comes with a clear report that a skeptical reviewer can inspect.

A valid outcome may also be a clean falsification: if the WPSR 1d candidate
does not work, preserve that negative result with enough evidence that we can
stop spending time on this branch.

## Why This Matters

The current locked 1d candidate is operationally useful but statistically weak:
it beats the zero-return baseline historically while losing to the realized
majority-sign baseline.

Current locked baseline, from `feasibility/forward/wti_lag_1d/lock.json`:

| Metric | Value |
| --- | ---: |
| target | `wti_front_1d_return_sign` |
| horizon/purge/embargo | `1/1/1` |
| scored residuals | `589` |
| HAC effective N | `524` |
| block-bootstrap effective N | `547` |
| model accuracy | `52.12%` |
| zero-return baseline accuracy | `47.03%` |
| majority baseline accuracy | `52.97%` |
| gain vs zero-return baseline | `+5.09 pp` |
| gain vs majority baseline | `-0.85 pp` |

The most valuable contribution is not another apparent backtest win. It is a
credible answer to whether WPSR value information can overcome this
majority-baseline weakness.

## Context You Should Read First

Start with this handoff file:

`https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/docs/operations/wpsr_1d_candidate_handoff.md`

It contains the current baseline, relevant files, data surfaces, known prior
work, locked-file constraints, and expected verification commands.

Important existing artifacts:

- Current forward lock:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/feasibility/forward/wti_lag_1d/lock.json`
- Current locked 1d baseline candidate:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/feasibility/candidates/wti_lag_1d/classical.py`
- Current 1d audit:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/feasibility/scripts/audit_wti_lag_1d_phase3.py`
- Existing WPSR 3d candidate:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/feasibility/candidates/wpsr_inventory_3d/classical.py`
- Existing WPSR 3d audit:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/feasibility/scripts/audit_wpsr_inventory_3d_phase3.py`
- WPSR first-release archive ingester:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/v2/ingest/eia_wpsr_archive.py`
- Current/latest WPSR EIA API ingester:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/v2/ingest/eia_wpsr.py`
- Main feasibility harness:
  `https://github.com/hrapson-spec/multi-desk-trading/blob/feasibility-harness-v0/feasibility/tractability_v1.py`

## Prior WPSR Result

There is already a WPSR inventory candidate for the 3-day target. It failed:

| Metric | Value |
| --- | ---: |
| target | `wti_front_3d_return_sign` |
| family | `wpsr` |
| horizon/purge/embargo | `3/3/3` |
| scored events | `227` |
| model accuracy | `50.22%` |
| zero baseline accuracy | `43.61%` |
| majority baseline accuracy | `56.39%` |
| gain vs zero baseline | `+6.61 pp` |
| HAC effective N | `176` |
| block-bootstrap effective N | `175` |
| verdict | `NON-ADMISSIBLE` |

Do not merely recreate this result with a different filename. The useful
question is whether a WPSR value candidate can work on the 1-day target under
the 1-day residual protocol.

## Freedom And Judgment

Use your expertise. You are not being asked to follow a prescribed modeling
recipe.

You may decide:

- Which WPSR value features are economically meaningful.
- Whether the existing trailing-change z-score definition is adequate.
- Whether Cushing, imports/exports, production, refinery utilization, product
  stocks, or combinations of these are the right state variables.
- Whether the candidate should include or exclude the strict WTI lag feature.
- What simple, defensible model class is appropriate for the sample size.
- What robustness checks are necessary for a skeptical promotion review.
- Whether the result should be killed rather than promoted.

The only hard requirement is that your choices must be pre-committed or
documented before result-dependent selection. Do not run a model zoo and then
write the preregistration after finding the winner.

## Hard Constraints

Do not weaken the evidence system.

You must preserve:

- Point-in-time correctness.
- The existing locked forward candidate.
- The existing forward lock integrity.
- The no-tuning-on-forward-outcomes rule.
- Free/public data constraints.
- The distinction between audit-only sign candidates and production desk
  outputs.

Do not edit these locked surfaces unless you explicitly stop and document why a
re-lock is unavoidable:

- `feasibility/forward/wti_lag_1d/lock.json`
- `feasibility/candidates/wti_lag_1d/classical.py`
- `feasibility/scripts/audit_wti_lag_1d_phase3.py`
- `feasibility/preregs/2026-04-29-wti_lag_all_calendar_1d.yaml`
- `feasibility/outputs/tractability_v1_1d_phase3_audit_wti_lag.json`
- `feasibility/outputs/wti_lag_1d_residuals.csv`
- `feasibility/tractability_v1.py`
- `contracts/target_variables.py`

The current forward automation may update timestamped status/report files while
you work. Treat those as live-state churn unless relevant to your task.

## Evidence Standards

A result is interesting only if it survives basic skepticism.

Your report should make these points explicit:

- What information was known at each decision timestamp?
- What exact target was predicted?
- What was the training window and test window?
- Were pre-2020 observations used only for warmup/training, or excluded
  entirely?
- How many events were available after purge/embargo?
- How many residuals were scored?
- What was model accuracy?
- What was zero-return baseline accuracy?
- What was majority-sign baseline accuracy?
- What was gain versus zero?
- What was gain versus majority?
- What were HAC and block-bootstrap effective N on residuals?
- Did any single year, feature, or regime dominate the result?
- Did simple placebo or date-shift checks fail as expected?

A result that beats zero but loses to majority is not enough.

## Deliverables

Produce a coherent local commit or patch containing the smallest set of
artifacts needed to support your conclusion.

Expected deliverables may include:

- A new pre-registration file for the WPSR 1d claim.
- A new audit-only candidate package.
- A new audit script.
- Residual CSV output.
- Residual-mode Phase 3 harness manifest.
- Human-readable report.
- Focused tests for feature construction, leakage safety, residual output, and
  baseline reporting.
- A short final summary explaining whether the candidate is admissible,
  non-admissible, or requires a clearly defined follow-up.

Do not register this as a production desk unless a separate promotion review
defines a controller-compatible decision unit.

## Acceptance Criteria

Minimum pass:

- Existing forward lock remains valid.
- Existing forecast chain remains valid.
- Existing tests relevant to WPSR, WTI lag, and forward evidence pass.
- New tests cover the new candidate.
- Report includes majority-baseline performance.
- The final verdict is unambiguous.

Strong pass:

- Gain versus majority baseline is positive and preferably >= `+2.0 pp`.
- HAC effective N >= `250`.
- Block-bootstrap effective N >= `250`.
- Robustness checks do not obviously destroy the result.
- The result is clear enough to decide whether to forward-lock a new candidate
  or kill the branch.

Clean failure:

- The candidate fails one or more gates, and the failure is clearly documented.
- The branch leaves behind reusable PIT-safe feature code or a strong reason to
  stop pursuing this class.
- No locked forward evidence is contaminated.

## Suggested Final Response Shape

When you are done, report:

- Verdict: admissible, non-admissible, or inconclusive.
- Files changed.
- Tests/commands run.
- Key metrics.
- Whether the existing forward lock still verifies.
- The single next decision you recommend.

Do not bury a failed majority-baseline result. That is the central question.

## Verification Commands

At minimum, run the narrow checks implied by your changes and verify the forward
lock:

```bash
cd /Users/henrirapson/projects/multi-desk-trading

.venv/bin/python - <<'PY'
from feasibility.scripts.forward_wti_lag_1d import verify_forecast_chain, verify_lock_integrity
print(verify_lock_integrity())
print(verify_forecast_chain())
PY
```

If feasible, also run:

```bash
.venv/bin/pytest tests/ -q
.venv/bin/ruff check .
```

`ruff format --check .` may report unrelated repo-wide formatting debt. At
minimum, format-check the files you touch.

## Important Mental Model

This is an evidence-quality task, not an optimization contest.

The best possible outcome is a simple causal candidate that clears the gates.
The second-best outcome is a clean falsification that lets us stop wasting
attention. The bad outcome is an overfit candidate that looks good historically
but weakens the forward evidence system.
