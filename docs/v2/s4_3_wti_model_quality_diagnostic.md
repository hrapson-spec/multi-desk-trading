# S4-3 WTI model-quality diagnostic

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Stage**: S4-3 local/free WTI model-quality diagnostic
- **Source**: `data/s4_0/free_source/raw/DCOILWTICO.csv`

## Objective

S4-3 moves from operational evidence toward model quality. It runs a
point-in-time walk-forward diagnostic on local/free WTI spot proxy data and
compares a simple ridge signal against conservative distributional baselines.

The purpose is not to claim profitability. The purpose is to decide whether the
current simple ML signal deserves further research or should be treated as a
model-quality debit.

## Method

Target:

- 5-day forward WTI log return.

Features:

- 1-day lagged return.
- 2-day lagged return.
- 5-day momentum.
- 20-day momentum.
- 20-day realised volatility.
- 60-day realised volatility.
- 20-day price z-score.

Protocol:

- Expanding walk-forward evaluation.
- 756-day warmup.
- 252 minimum known training samples.
- 5-day horizon.
- Ridge alpha: 10.0.
- Training rows are included only when their 5-day outcome would have been
  known before the decision row.

Baselines:

- Historical empirical 5-day return quantiles.
- Zero-mean Gaussian distribution using historical 5-day target volatility.

Scoring:

- Mean pinball loss.
- Approximate CRPS from fixed quantiles.
- Directional accuracy of the predicted median.
- Diebold-Mariano HAC comparison on per-row mean pinball loss.

## Result

| Metric | Result |
|---|---:|
| `rows_total` | 10142 |
| `decisions` | 9381 |
| `min_train_samples_observed` | 692 |
| `max_train_samples_observed` | 10072 |
| `model_pinball_loss` | 0.0101535604 |
| `empirical_pinball_loss` | 0.0099992225 |
| `zero_gaussian_pinball_loss` | 0.0100873280 |
| `model_crps` | 0.0282836815 |
| `empirical_crps` | 0.0278908143 |
| `zero_gaussian_crps` | 0.0281232229 |
| `pinball_improvement_vs_empirical` | -0.0154349898 |
| `pinball_improvement_vs_zero_gaussian` | -0.0065659042 |
| `crps_improvement_vs_empirical` | -0.0140858973 |
| `crps_improvement_vs_zero_gaussian` | -0.0057055535 |
| `directional_accuracy` | 0.5077283872 |
| `DM mean_diff vs empirical` | 0.0001543379 |
| `DM stat vs empirical` | 3.2740544266 |
| `DM mean_diff vs zero_gaussian` | 0.0000662324 |
| `DM stat vs zero_gaussian` | 1.3908941768 |
| `promoted_for_research` | false |
| `result_hash` | `9a779a7659c4c1dffcfea9385a1642b411f92ec4e7950f681301d34f9bb3c66a` |

## Interpretation

The simple ridge signal is not promotable. It is slightly worse than both
baselines on pinball loss and CRPS. Directional accuracy is barely above 50%
and does not compensate for weaker distributional scoring.

The DM comparison against the empirical baseline is especially clear: positive
mean loss difference means the model loss is higher than the empirical
baseline. The current ridge feature stack should therefore be treated as an
engineering diagnostic, not an alpha signal.

## Non-Claims

- Not a live trading result.
- Not an investment-performance result.
- Not a production-readiness result.
- Uses local/free WTI spot proxy data, not licensed CL order-book data.

## Verification

- `uv run pytest tests/v2/s4_0/test_model_quality.py -q` -> 4 passed
- `uv run pytest tests/v2/s4_0 -q` -> 42 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 277 passed

## Next Engineering Implication

The next work should not be production hardening. It should be signal research:

- Add carry/term-structure proxies where free data permits.
- Add inventory/supply shocks from EIA weekly petroleum status data.
- Add CFTC positioning features.
- Add event calendar flags.
- Re-run the same S4-3 gate before promoting any model-quality claim.

S4-3A has now added the PIT-safe exogenous feature hook needed for that work.
Feature rows are merged by backward as-of release timestamp, not by economic
observation date.
