# S4-2 MBP-10 simulated-fill results

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Stage**: S4-2 MBP-10 simulated-fill drill
- **Report hash**: `b27b20eade1fceb5d8cdea729f0c73eac4d1c298857ec690033aba01c657f63c`

## Fixture

The drill used one synthetic CLM6 MBP-10 snapshot with three displayed levels:

| Level | Bid price | Bid size | Ask price | Ask size |
|---:|---:|---:|---:|---:|
| 1 | 74.99 | 10 | 75.01 | 10 |
| 2 | 74.98 | 20 | 75.02 | 20 |
| 3 | 74.97 | 30 | 75.03 | 30 |

Orders:

| Order | Side | Quantity | Limit | Expected behavior |
|---|---|---:|---:|---|
| `buy_full` | buy | 15 | none | Full fill across ask levels 1-2. |
| `sell_full` | sell | 12 | 74.98 | Full fill across bid levels 1-2. |
| `buy_partial` | buy | 100 | 75.02 | Partial fill through ask level 2, residual remains. |
| `sell_unfilled` | sell | 5 | 75.10 | No bid satisfies the limit. |

## Aggregate Metrics

| Metric | Result |
|---|---:|
| `orders_total` | 4 |
| `orders_filled` | 2 |
| `orders_partially_filled` | 1 |
| `orders_unfilled` | 1 |
| `requested_quantity` | 132 |
| `filled_quantity` | 57 |
| `residual_quantity` | 75 |
| `fill_ratio` | 0.4318181818 |
| `average_fill_price` | 75.0098245614 |
| `average_slippage_vs_top` | 0.0047368421 |
| `max_depth_consumed` | 2 |
| `levels_consumed_total` | 6 |
| `book_validation_errors` | 0 |
| `prohibited_claims` | `queue_position_accuracy` |
| `queue_position_claimed` | false |
| `ok` | true |

## Per-Order Results

| Order | Filled | Residual | Avg fill | Top price | Slippage vs top | Levels consumed | Errors |
|---|---:|---:|---:|---:|---:|---:|---|
| `buy_full` | 15 | 0 | 75.0133333333 | 75.01 | 0.0033333333 | 2 | none |
| `sell_full` | 12 | 0 | 74.9883333333 | 74.99 | 0.0016666667 | 2 | none |
| `buy_partial` | 30 | 70 | 75.0166666667 | 75.01 | 0.0066666667 | 2 | none |
| `sell_unfilled` | 0 | 5 | n/a | 74.99 | n/a | 0 | none |

## Verification

- `uv run pytest tests/v2/s4_0 -q` -> 30 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 265 passed

## Interpretation

The drill proves bounded MBP-10 depth-aware simulated fills on synthetic data.
It does not prove queue position, real exchange execution quality, hidden
liquidity, order-level reconstruction, profitability, or production readiness.

The queue-position, hidden-liquidity, and profitability gaps are now covered by
`s4_2a_synthetic_claim_diagnostics.md` as synthetic diagnostics only. Those
diagnostics measure the mechanics under declared assumptions while keeping real
queue, real hidden-liquidity, and real profitability claims false.
