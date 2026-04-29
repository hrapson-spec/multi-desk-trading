# Phase 3 Audit — FOMC → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-fomc_wti_3d.yaml`  
**Manifest created**: 2026-04-29T12:16:32.014658Z  
**Report written**: 2026-04-29T12:16:32Z  
**Audit-only**: yes — no v1/v2 desk registration implied.

---

## Harness parameters

| Parameter | Value |
| --- | --- |
| families | wpsr, fomc, opec_ministerial |
| horizon_days | 3 |
| purge_days | 3 |
| embargo_days | 3 |
| warmup_weeks | 52 |
| refit_cadence | monthly |

---

## Gate 1 — effective N waterfall

| Stage | N |
| --- | --- |
| n_after_purge_embargo | 365 |
| HAC effective N (Newey-West, residuals) | 224 |
| block-bootstrap effective N (residuals) | 215 |
| n_star (overall, harness decision) | 215 |

---

## Prereg threshold comparisons

Walk-forward residuals: 310 events (239 unique decision dates after multi-family dedup).  
Post-2020 sample: 476 observations; WTI 3d return positive rate = 53.36%.  
Zero-return baseline accuracy = max(53.36%, 46.64%) = **53.36%**.

| Threshold | Prereg floor | Measured | Pass? |
| --- | --- | --- | --- |
| Directional accuracy delta vs zero-return baseline | >= 5.0 pp | +2.45 pp (55.81% − 53.36%) | FAIL |
| HAC effective N (Newey-West on residuals) | >= 250 | 224 | FAIL |
| Block-bootstrap effective N (residuals) | >= 250 | 215 | FAIL |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

All three prereg thresholds fail. HAC N = 224 < 250; bootstrap N = 215 < 250; directional accuracy delta = +2.45 pp < 5.0 pp floor. Candidate does not clear Phase 3 gate.

Spec v1 §13 admission thresholds: HAC N >= 250 and bootstrap N >= 250 on the residual series (not the raw target). Walk-forward residuals were computed with a 52-week warmup and monthly refit per the pre-reg outer_protocol.

---

## Interpretation

The FOMC → WTI 3d hypothesis is non-admissible on all three axes. The directional accuracy improvement over the zero-return baseline is modest (2.45 pp), well below the 5 pp prereg floor, suggesting the logistic regression on `fomc_event_indicator` + `wti_5d_lagged_return` does not extract a statistically meaningful edge at the 3-day horizon in the 2020-forward sample. Crucially, the HAC and bootstrap effective-N both fall below 250: the residual series carries non-trivial serial dependence (Newey-West rho-sum = 0.191), which inflates variance and reduces the information content of the 365-observation post-2020 window to approximately 215 independent draws — insufficient for the spec floor. The 3d horizon is shorter than the 5d horizon tested in prior audits; the faster return cycle may reduce the FOMC signal-to-noise ratio by compressing the window in which monetary policy expectations transmit to oil. These results are consistent with the S4-4 Track A finding that event-driven approaches at short horizons face cost and dependence headwinds. A NON-ADMISSIBLE result is a valid deliverable; it bounds the hypothesis space and rules out simple logistic-regression exploitation of FOMC dates at 3d.

---

## Harness decision block

```json
{
  "action": "remove_foundation_models_from_harness",
  "min_effective_n": 215,
  "rule": "continue_small_model_only"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
