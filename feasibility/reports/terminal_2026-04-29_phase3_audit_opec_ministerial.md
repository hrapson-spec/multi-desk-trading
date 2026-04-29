# Phase 3 Audit — OPEC Ministerial → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-opec_ministerial_wti_3d.yaml`  
**Manifest created**: 2026-04-29T13:32:58.582796Z  
**Report written**: 2026-04-29T13:32:58Z  
**Audit-only**: yes — no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | opec_ministerial |
| horizon_days | 3 |
| purge_days | 3 |
| embargo_days | 3 |
| warmup_weeks | 52 |
| refit_cadence | monthly |
| data_quality | release_lag_safe_revision_unknown curated calendar |

---

## Gate 1 — directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 36 |
| model_accuracy | 41.67% |
| zero_return_baseline_accuracy | 50.00% |
| majority_baseline_accuracy | 50.00% |
| accuracy_gain_vs_zero_return_baseline | -8.33 pp |
| required_gain | 5.00 pp |

---

## Gate 2 — effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 47 |
| HAC effective N (Newey-West, residuals) | 27 |
| block-bootstrap effective N (residuals) | 36 |
| n_star (overall, harness decision) | 27 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

accuracy gain = -8.33 pp < 5.00 pp; HAC N = 27 < 250; bootstrap N = 36 < 250. Candidate does not clear Phase 3 gate.

---

## Harness decision block

```json
{
  "action": "write_terminal_report_do_not_build_harness",
  "min_effective_n": 27,
  "rule": "stop"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
