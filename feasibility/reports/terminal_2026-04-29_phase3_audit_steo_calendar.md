# Phase 3 Audit — STEO Calendar → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-steo_calendar_wti_3d.yaml`  
**Manifest created**: 2026-04-29T13:53:20.916247Z  
**Report written**: 2026-04-29T13:53:21Z  
**Audit-only**: yes — no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | steo |
| horizon_days | 3 |
| purge_days | 3 |
| embargo_days | 3 |
| warmup_weeks | 52 |
| refit_cadence | monthly |
| data_quality | calendar_only_no_steo_table_values |

> Caveat: this audit uses the v1.0 PIT release calendar only. It does not test STEO forecast table values, which require a v1.1 table parser.

---

## Gate 1 — directional skill

| Metric | Value |
| --- | ---: |
| scored_events | 64 |
| model_accuracy | 57.81% |
| zero_return_baseline_accuracy | 48.44% |
| majority_baseline_accuracy | 51.56% |
| accuracy_gain_vs_zero_return_baseline | 9.38 pp |
| required_gain | 5.00 pp |

---

## Gate 2 — effective N waterfall

| Stage | N |
| --- | ---: |
| n_after_purge_embargo | 76 |
| HAC effective N (Newey-West, residuals) | 47 |
| block-bootstrap effective N (residuals) | 50 |
| n_star (overall, harness decision) | 47 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

HAC N = 47 < 250; bootstrap N = 50 < 250. Candidate does not clear Phase 3 gate.

---

## Harness decision block

```json
{
  "action": "write_terminal_report_do_not_build_harness",
  "min_effective_n": 47,
  "rule": "stop"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
