# Phase 3 Audit - WPSR Inventory -> WTI 1d Return Sign

**Pre-reg**: `feasibility/preregs/2026-05-01-wpsr_inventory_wti_1d.yaml`
**Manifest created**: 2026-05-01T07:56:39.737723Z
**Report written**: 2026-05-01T07:56:39Z
**Audit-only**: yes - no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | wpsr |
| horizon_days | 1 |
| purge_days | 1 |
| embargo_days | 1 |
| min_train_events | 52 |
| refit_cadence | monthly |
| feature_family | WPSR-only trailing weekly-change z-scores |
| training_history | pre-2020 rows allowed for warmup; labels gated before refit |

---

## Gate 1 - directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 327 |
| model_accuracy | 47.40% |
| zero_return_baseline_accuracy | 48.01% |
| majority_baseline_accuracy | 51.99% |
| accuracy_gain_vs_zero_return_baseline | -0.61 pp |
| required_gain_vs_zero | 5.00 pp |
| accuracy_gain_vs_majority_sign_baseline | -4.59 pp |
| required_gain_vs_majority | > 0.00 pp |
| preferred_gain_vs_majority | 2.00 pp |

---

## Gate 2 - effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 327 |
| HAC effective N (Newey-West, residuals) | 318 |
| block-bootstrap effective N (residuals) | 327 |
| n_star (overall, harness decision) | 318 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

accuracy gain vs zero = -0.61 pp < 5.00 pp; accuracy gain vs majority = -4.59 pp <= 0.00 pp. Candidate does not clear Phase 3 gate.

---

## Harness decision block

```json
{
  "action": "continue_per_plan",
  "min_effective_n": 318,
  "rule": "continue"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
