# Phase 3 Audit — PSM Calendar → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-psm_calendar_wti_3d.yaml`  
**Manifest created**: 2026-04-29T13:50:25.434768Z  
**Report written**: 2026-04-29T13:50:25Z  
**Audit-only**: yes — no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | psm |
| horizon_days | 3 |
| purge_days | 3 |
| embargo_days | 3 |
| warmup_weeks | 52 |
| refit_cadence | monthly |
| data_quality | calendar_only_no_psm_table_values |

> Caveat: this audit uses the v1.0 PIT release calendar only. It does not test EIA-914/PSM production-surprise values, which require a v1.1 table parser.

---

## Gate 1 — directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 63 |
| model_accuracy | 53.97% |
| zero_return_baseline_accuracy | 41.27% |
| majority_baseline_accuracy | 58.73% |
| accuracy_gain_vs_zero_return_baseline | 12.70 pp |
| required_gain | 5.00 pp |

---

## Gate 2 — effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 75 |
| HAC effective N (Newey-West, residuals) | 58 |
| block-bootstrap effective N (residuals) | 63 |
| n_star (overall, harness decision) | 58 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

HAC N = 58 < 250; bootstrap N = 63 < 250. Candidate does not clear Phase 3 gate.

---

## Harness decision block

```json
{
  "action": "write_terminal_report_do_not_build_harness",
  "min_effective_n": 58,
  "rule": "stop"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
