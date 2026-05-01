# Phase 3 Audit - WTI Lag -> WTI 1d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-wti_lag_all_calendar_1d.yaml`  
**Manifest created**: 2026-04-29T14:12:37.698685Z  
**Report written**: 2026-04-29T14:12:37Z  
**Audit-only**: yes - no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | wpsr,fomc,steo,opec_ministerial,psm,gpr |
| horizon_days | 1 |
| purge_days | 1 |
| embargo_days | 1 |
| min_train_events | 52 |
| refit_cadence | monthly |
| feature | strict previous-trading-day WTI 1d log return |
| caveat | post_3d_pivot_exploratory_success_forward_lock_required |

---

## Gate 1 - directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 589 |
| model_accuracy | 52.12% |
| zero_return_baseline_accuracy | 47.03% |
| majority_baseline_accuracy | 52.97% |
| accuracy_gain_vs_zero_return_baseline | 5.09 pp |
| required_gain | 5.00 pp |

---

## Gate 2 - effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 648 |
| HAC effective N (Newey-West, residuals) | 524 |
| block-bootstrap effective N (residuals) | 547 |
| n_star (overall, harness decision) | 524 |

---

## Phase 3 verdict

**ADMISSIBLE_PROVISIONAL**

All numeric Phase 3 thresholds cleared. Because this is a post-3d-pivot candidate discovered after exploratory screening, promotion still requires a forward lock and rerun.

---

## Harness decision block

```json
{
  "action": "continue_per_plan",
  "min_effective_n": 524,
  "rule": "continue"
}
```

---

*Audit-only report. Does not constitute a production promotion recommendation.*
