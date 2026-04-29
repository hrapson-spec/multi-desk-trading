# WTI Lag 1d Robustness Diagnostics

**Created**: 2026-04-29T14:26:23Z  
**Mode**: no-tuning diagnostics on the locked historical candidate.

## Overall

| Metric | Value |
| --- | ---: |
| scored_events | 589 |
| accuracy | 52.12% |
| gain_vs_zero_return_baseline | 5.09 pp |
| gain_vs_majority_baseline | -0.85 pp |

## Family Slices

| Family | N | Accuracy | Gain vs zero | Gain vs majority |
| --- | ---: | ---: | ---: | ---: |
| fomc | 3 | 66.67% | 33.33 pp | 0.00 pp |
| gpr | 221 | 50.23% | 2.71 pp | -2.26 pp |
| opec_ministerial | 11 | 54.55% | 9.09 pp | 0.00 pp |
| psm | 62 | 48.39% | 0.00 pp | -3.23 pp |
| wpsr | 292 | 54.11% | 7.53 pp | 0.68 pp |

## Time Slices

| Window | N | Accuracy | Gain vs zero | Gain vs majority |
| --- | ---: | ---: | ---: | ---: |
| 2020_2021 | 145 | 53.79% | 10.34 pp | -2.76 pp |
| 2022_2023 | 206 | 52.43% | 5.34 pp | -0.49 pp |
| 2024_2026 | 238 | 50.84% | 1.68 pp | 0.00 pp |
| ex_2020 | 546 | 52.75% | 5.86 pp | -0.37 pp |

## Placebo Date Shifts

| Shift rows | N | Accuracy | Gain vs zero |
| ---: | ---: | ---: | ---: |
| -5 | 584 | 53.08% | 6.16 pp |
| -2 | 587 | 51.96% | 5.11 pp |
| 2 | 587 | 52.47% | 5.45 pp |
| 5 | 584 | 53.08% | 6.34 pp |

## Decision

Forward holdout remains mandatory. The historical candidate clears the registered zero-return baseline but does not clear the realized majority-sign baseline, so promotion review must treat majority skill as an explicit hurdle.
