# Phase 3 Audit — GPR Shock Weeks → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-gpr_shock_wti_3d.yaml`  
**Manifest created**: 2026-04-29T13:42:36.071214Z  
**Report written**: 2026-04-29T13:42:36Z  
**Audit-only**: yes — no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | gpr |
| horizon_days | 3 |
| purge_days | 3 |
| embargo_days | 3 |
| warmup_weeks | 52 |
| refit_cadence | monthly |
| gpr_snapshot_rows | 15092 |
| gpr_snapshot_range | 1985-01-01 to 2026-04-27 |
| data_quality | current_public_snapshot_not_true_PIT_vintage |

---

## Gate 1 — directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 221 |
| model_accuracy | 48.87% |
| zero_return_baseline_accuracy | 50.68% |
| majority_baseline_accuracy | 50.68% |
| accuracy_gain_vs_zero_return_baseline | -1.81 pp |
| required_gain | 5.00 pp |

---

## Gate 2 — effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 291 |
| HAC effective N (Newey-West, residuals) | 164 |
| block-bootstrap effective N (residuals) | 168 |
| n_star (overall, harness decision) | 164 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

accuracy gain = -1.81 pp < 5.00 pp; HAC N = 164 < 250; bootstrap N = 168 < 250; GPR values came from current public snapshot, not true PIT vintages. Candidate does not clear Phase 3 gate.

---

## Harness decision block

```json
{
  "action": "remove_foundation_models_from_harness",
  "min_effective_n": 164,
  "rule": "continue_small_model_only"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
