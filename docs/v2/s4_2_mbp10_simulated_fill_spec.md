# S4-2 MBP-10 simulated-fill drill specification

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Predecessor**: `s4_1_closeout.md`
- **Stage**: S4-2 MBP-10 simulated-fill drill

## Objective

S4-2 proves that synthetic MBP-10 snapshots can support a bounded,
depth-aware simulated-fill drill without claiming queue-position realism.

## Metrics

The drill must report:

- `orders_total`
- `orders_filled`
- `orders_partially_filled`
- `orders_unfilled`
- `requested_quantity`
- `filled_quantity`
- `residual_quantity`
- `fill_ratio`
- `average_fill_price`
- `average_slippage_vs_top`
- `max_depth_consumed`
- `levels_consumed_total`
- `book_validation_errors`
- `prohibited_claims`
- `queue_position_claimed`

## Pass Criteria

- All valid fixture books pass MBP-10 validation.
- Invalid books or invalid orders are reported as errors.
- Fill quantity never exceeds displayed MBP size.
- Limit prices constrain fills.
- Partial fills are explicitly reported.
- Average fill price is size-weighted.
- Slippage is measured against top-of-book, not against a queue model.
- `queue_position_claimed` is false.
- `queue_position_accuracy` remains a prohibited claim.

## Non-Claims

- No MBO/order-level reconstruction.
- No queue-position accuracy.
- No hidden liquidity, implied order, iceberg, or pro-rata model.
- No real execution-quality claim.
- No profitability or production-readiness claim.

## Exit Decision

S4-2 is complete when the executable MBP-10 fill drill passes focused tests,
full v2 regression remains green, and the PMO dashboard records the metric
results.

## Current Verification

- `uv run pytest tests/v2/s4_0 -q` -> 30 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 265 passed
- Metric results: `s4_2_mbp10_simulated_fill_results.md`
