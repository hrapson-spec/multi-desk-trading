# Phase 3 Audit — WPSR Inventory Surprise → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-wpsr_inventory_wti_3d.yaml`  
**Manifest created**: 2026-04-29T13:24:22.617789Z  
**Report written**: 2026-04-29T13:24:22Z  
**Audit-only**: yes — no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | wpsr |
| horizon_days | 3 |
| purge_days | 3 |
| embargo_days | 3 |
| warmup_weeks | 52 |
| refit_cadence | monthly |

---

## Gate 1 — directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 227 |
| model_accuracy | 50.22% |
| zero_return_baseline_accuracy | 43.61% |
| majority_baseline_accuracy | 56.39% |
| accuracy_gain_vs_zero_return_baseline | 6.61 pp |
| required_gain | 5.00 pp |

---

## Gate 2 — effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 272 |
| HAC effective N (Newey-West, residuals) | 176 |
| block-bootstrap effective N (residuals) | 175 |
| n_star (overall, harness decision) | 175 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

HAC N = 176 < 250; bootstrap N = 175 < 250. Candidate does not clear Phase 3 gate.

---

## Harness decision block

```json
{
  "action": "remove_foundation_models_from_harness",
  "min_effective_n": 175,
  "rule": "continue_small_model_only"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
