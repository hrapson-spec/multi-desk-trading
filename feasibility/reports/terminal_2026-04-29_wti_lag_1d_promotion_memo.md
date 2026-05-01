# WTI Lag 1d Promotion Memo

Created: 2026-04-29

## Decision

**Do not promote yet. Start forward holdout.**

The all-calendar WTI lag 1d candidate clears the numeric historical Phase 3
thresholds, but the pass is not promotion-grade because it was discovered after
the 3d candidate set failed. The candidate is now locked for forward scoring at:

- `feasibility/forward/wti_lag_1d/lock.json`
- `feasibility/forward/wti_lag_1d/lock_report.md`

## Locked Historical Facts

| Metric | Value |
| --- | ---: |
| target | `wti_front_1d_return_sign` |
| horizon/purge/embargo | 1/1/1 days |
| families | `wpsr,fomc,steo,opec_ministerial,psm,gpr` |
| scored_residuals | 589 |
| n_after_purge_embargo | 648 |
| HAC effective N | 524 |
| block-bootstrap effective N | 547 |
| model_accuracy | 52.12% |
| gain_vs_zero_return_baseline | +5.09 pp |
| gain_vs_majority_baseline | -0.85 pp |

## Forward Holdout State

The forward machinery has been initialized:

- queue: `feasibility/forward/wti_lag_1d/event_queue.csv`
- forecasts: `feasibility/forward/wti_lag_1d/forecasts.jsonl`
- outcomes: `feasibility/forward/wti_lag_1d/outcomes.csv`
- monitor: `feasibility/forward/wti_lag_1d/monitor_report.md`

Initial queue size is 42 events over the next 120 days. No forecasts were
written at initialization because no queued event had reached its post-lock
decision timestamp at the run time.

## Robustness Findings

No-tuning diagnostics are recorded at:

- `feasibility/outputs/wti_lag_1d_robustness.json`
- `feasibility/reports/terminal_2026-04-29_wti_lag_1d_robustness.md`

Material findings:

- Skill is concentrated in WPSR and sparse OPEC/FOMC slices.
- 2024-2026 gain vs zero falls to +1.68 pp, so recent-period robustness is weak.
- Date-shift placebos are not cleanly killed; that suggests broad sign/regime
  imbalance may explain part of the edge.
- The majority-baseline gap is a real promotion debit even though the registered
  zero-return baseline is cleared.

## Promotion Criteria

Promotion review can reopen only after all of the following are true:

1. At least 60 forward events are scored and resolved with the locked files
   unchanged.
2. Preferred: 100 forward events scored and resolved.
3. Forward accuracy remains above the zero-return baseline.
4. Forward accuracy also beats the realized majority-sign baseline.
5. No feature, threshold, model-class, hyperparameter, family list, refit cadence,
   purge, or embargo setting changes are made after lock.

## Debits

| Debit | Severity | Status |
| --- | --- | --- |
| D-WTI-LAG-1D-001 post-hoc discovery after 3d failures | blocking for promotion | open |
| D-WTI-LAG-1D-002 trails historical majority-sign baseline | major | open |
| D-WTI-LAG-1D-003 FRED WTI spot proxy is non-executable | major | open |
| D-STOOQ-KEY-001 Stooq futures endpoint requires key/captcha for live retry | operational | open |

## Next Operational Step

Run the forward holdout script after each queued event's decision timestamp and
again after the 1d outcome can be observed:

```bash
.venv/bin/python -m feasibility.scripts.forward_wti_lag_1d all
```

That command appends forecasts, resolves matured outcomes, and refreshes the
monitor without changing the locked candidate.

## Verification

- `.venv/bin/pytest tests/ -q`: **931 passed, 1 skipped, 17 warnings**
- `.venv/bin/ruff check .`: clean
- `.venv/bin/ruff format --check` on touched code/test files: clean
- `.venv/bin/ruff format --check .`: not clean due unrelated repo-wide
  formatting drift.
- `.venv/bin/mypy .`: not clean; 1,423 existing-style repo errors across 190
  files, mostly missing third-party stubs and untyped legacy tests/modules.
