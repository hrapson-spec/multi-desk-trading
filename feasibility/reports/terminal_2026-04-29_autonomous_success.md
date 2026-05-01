# Autonomous Follow-up Success

Created: 2026-04-29

## Result

The first numerically admissible branch is a **1d all-calendar WTI lag**
candidate:

| Metric | Value |
| --- | ---: |
| target | `wti_front_1d_return_sign` |
| families | `wpsr,fomc,steo,opec_ministerial,psm,gpr` |
| n_after_purge_embargo | 648 |
| scored_residuals | 589 |
| model_accuracy | 52.12% |
| zero_return_baseline_accuracy | 47.03% |
| accuracy_gain | +5.09 pp |
| HAC effective N | 524 |
| block-bootstrap effective N | 547 |
| harness decision | `continue_per_plan` |

Report:
`feasibility/reports/terminal_2026-04-29_phase3_audit_wti_lag_1d.md`

Manifest:
`feasibility/outputs/tractability_v1_1d_phase3_audit_wti_lag.json`

## What Changed

1. Retried the blocked Stooq price-spine path. It is still blocked because the
   relevant Stooq futures endpoint now requires an API key/captcha flow.
2. Built and live-ran a value-bearing STEO archive ingester:
   `v2/ingest/eia_steo_value_archive.py`.
3. Backfilled 76 official EIA STEO Excel vintages, producing 46,296 long-form
   forecast rows in PIT under `dataset=steo_value_archive`.
4. Tested STEO value state on the 3d event stream. It did not clear residual
   effective-N gates.
5. Pivoted to shorter horizons. The 1d strict previous-trading-day WTI lag
   candidate cleared all numeric Phase 3 thresholds.

## Caveat

This is **ADMISSIBLE_PROVISIONAL**, not promotion-ready. It was discovered
after the 3d candidate set failed, so the historical pass is exploratory. The
forward lock is now written at `feasibility/forward/wti_lag_1d/lock.json`.
Future events must be scored without changing features, thresholds, model class,
family list, or refit cadence.

## Forward Holdout

| Artifact | Path |
| --- | --- |
| lock | `feasibility/forward/wti_lag_1d/lock.json` |
| queue | `feasibility/forward/wti_lag_1d/event_queue.csv` |
| forecasts | `feasibility/forward/wti_lag_1d/forecasts.jsonl` |
| outcomes | `feasibility/forward/wti_lag_1d/outcomes.csv` |
| monitor | `feasibility/forward/wti_lag_1d/monitor_report.md` |
| robustness | `feasibility/reports/terminal_2026-04-29_wti_lag_1d_robustness.md` |
| promotion memo | `feasibility/reports/terminal_2026-04-29_wti_lag_1d_promotion_memo.md` |

Initial forward queue: 42 events over the next 120 days. Forecast count at
initialization: 0, because the first queued event had not yet reached its
post-lock decision timestamp.

Additional caveat: the model beats the registered zero-return baseline by
+5.09 pp, but trails the realized majority-sign baseline by -0.85 pp. Promotion
review must therefore require both zero-baseline and majority-baseline checks.

## Verification

- `.venv/bin/pytest tests/ -q`: **931 passed, 1 skipped, 17 warnings**
- `.venv/bin/ruff check .`: clean
- `.venv/bin/ruff format --check` on touched code/test files: clean
- `.venv/bin/ruff format --check .`: not clean due pre-existing repo-wide
  formatting drift in unrelated files; left untouched.
- `.venv/bin/mypy .`: not clean; reports 1,423 repo-level errors across
  untyped legacy modules/tests and missing third-party stubs. No broad mypy
  config changes were made to mask this.
