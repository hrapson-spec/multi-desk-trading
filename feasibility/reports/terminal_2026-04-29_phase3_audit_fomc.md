# Phase 3 Audit — FOMC → WTI 3d Return Sign

**Pre-reg**: `feasibility/preregs/2026-04-29-fomc_wti_3d.yaml`  
**Manifest created**: 2026-04-29T13:34:42.435131Z  
**Report written**: 2026-04-29T13:34:42Z  
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
| n_after_purge_embargo | 285 |
| HAC effective N (Newey-West, residuals) | 224 |
| block-bootstrap effective N (residuals) | 236 |
| n_star (overall, harness decision) | 224 |

---

## Phase 3 verdict

**NON-ADMISSIBLE**

HAC N = 224 < 250; bootstrap N = 236 < 250. Candidate does not clear Phase 3 gate.

Spec v1 §13 admission thresholds: HAC N >= 250 and bootstrap N >= 250 on the residual series (not the raw target). Walk-forward residuals were computed with a 52-week warmup and monthly refit per the pre-reg outer_protocol.

---

## Harness decision block

```json
{
  "action": "remove_foundation_models_from_harness",
  "min_effective_n": 224,
  "rule": "continue_small_model_only"
}
```

---

*Audit-only report. Does not constitute a promotion recommendation.*
