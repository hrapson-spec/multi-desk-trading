# WTI Lag 1d Forward Monitor

**Lock id**: `dcc249c4d25a8890`  
**Updated**: 2026-04-29T18:52:19Z  
**Status**: forward holdout initialized; no tuning permitted.  
**Lock integrity**: ok  

## Counts

| Item | Count |
| --- | ---: |
| queued_events | 42 |
| forecasts_written | 1 |
| feature_stale_or_missing_forecasts | 0 |
| outcomes_resolved | 0 |
| missed_unscored_events | 0 |

## Forward Baselines

| Metric | Value |
| --- | ---: |
| resolved_events | 0 |

## Historical Lock Metrics

| Metric | Value |
| --- | ---: |
| HAC effective N | 524 |
| block-bootstrap effective N | 547 |
| gain_vs_zero_return_baseline | 5.09 pp |
| gain_vs_majority_baseline | -0.85 pp |

## Next Queue Events

| decision_ts | family | event_type | source_method |
| --- | --- | --- | --- |
| 2026-05-01T13:05:00Z | gpr | gpr_weekly_release | weekly_friday_rule_v1 |
| 2026-05-06T14:35:00Z | wpsr | weekly_release_rule_v1 | wednesday_1030_et_rule_plus_5m_guard |
| 2026-05-08T13:05:00Z | gpr | gpr_weekly_release | weekly_friday_rule_v1 |
| 2026-05-12T16:05:00Z | steo | steo_release | second_tuesday_rule_v1 |
| 2026-05-13T14:35:00Z | wpsr | weekly_release_rule_v1 | wednesday_1030_et_rule_plus_5m_guard |
| 2026-05-15T13:05:00Z | gpr | gpr_weekly_release | weekly_friday_rule_v1 |
| 2026-05-20T14:35:00Z | wpsr | weekly_release_rule_v1 | wednesday_1030_et_rule_plus_5m_guard |
| 2026-05-22T13:05:00Z | gpr | gpr_weekly_release | weekly_friday_rule_v1 |
| 2026-05-27T14:35:00Z | wpsr | weekly_release_rule_v1 | wednesday_1030_et_rule_plus_5m_guard |
| 2026-05-29T13:05:00Z | gpr | gpr_weekly_release | weekly_friday_rule_v1 |

## Promotion Guard

Promotion review remains blocked until at least 60 forward events are scored and resolved with unchanged files, unchanged thresholds, and explicit zero-return plus majority-baseline checks.
