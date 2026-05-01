# S4-3A exogenous feature hook

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Predecessor**: `s4_3_wti_model_quality_diagnostic.md`
- **Stage**: S4-3A model-quality feature expansion

## Objective

S4-3 showed that the price-only ridge signal is not promotable. S4-3A adds the
feature plumbing needed for real observable WTI drivers without changing the
walk-forward gate.

The model-quality diagnostic now accepts release-timestamped exogenous feature
frames and merges them into each decision row using backward as-of semantics.
This is the required path for EIA inventory/supply features, CFTC positioning
features, and event-calendar features.

## Control Rule

Exogenous features must use a UTC `DatetimeIndex` representing when the data is
decision-eligible, not when the underlying economic observation occurred.

Merge rule:

```text
decision_ts receives the latest exogenous row with release_ts <= decision_ts
```

This prevents using Tuesday CFTC positions before the Friday release, or weekly
EIA observations before publication.

## Implementation

Updated:

- `v2/s4_0/model_quality.py`
- `tests/v2/s4_0/test_model_quality.py`

The report now records `exogenous_feature_columns`, for example:

```json
["exog_inventory_surprise"]
```

## Verification

- `uv run pytest tests/v2/s4_0/test_model_quality.py -q` -> 5 passed
- `uv run pytest tests/v2/s4_0 -q` -> 43 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 278 passed

## Next Engineering Implication

The next signal-improvement work should implement one concrete exogenous data
adapter and re-run S4-3:

- CFTC COT WTI managed-money / producer-merchant net positioning.
- EIA weekly crude/product inventory and refinery-run surprises.
- Release-calendar event flags.

No model-quality claim should be promoted until the same S4-3 walk-forward gate
beats both the empirical and zero-Gaussian baselines on pinball and CRPS.
