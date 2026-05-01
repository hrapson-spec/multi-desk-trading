# WTI Lag 1d Forward Lock

**Lock id**: `dcc249c4d25a8890`  
**Locked at**: 2026-04-29T14:25:52Z  
**Status**: audit-only provisional; forward holdout required.

## Frozen Candidate

| Field | Value |
| --- | --- |
| target | wti_front_1d_return_sign |
| families | wpsr,fomc,steo,opec_ministerial,psm,gpr |
| horizon/purge/embargo | 1/1/1 days |
| feature | strict previous-trading-day WTI 1d log return |
| model | fixed-hyperparameter logistic regression |

## Historical Gate Metrics

| Metric | Value |
| --- | ---: |
| n_after_purge_embargo | 648 |
| scored_residuals | 589 |
| HAC effective N | 524 |
| block-bootstrap effective N | 547 |
| model_accuracy | 52.12% |
| gain_vs_zero_return_baseline | 5.09 pp |
| gain_vs_majority_baseline | -0.85 pp |

## Promotion State

Not promoted. This lock starts a forward holdout because the candidate was found after exploratory screening and because the majority baseline remains a material debit.
