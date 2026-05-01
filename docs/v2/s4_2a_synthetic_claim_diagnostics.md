# S4-2A synthetic claim diagnostics

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Predecessor**: `s4_2_mbp10_simulated_fill_results.md`
- **Stage**: S4-2A synthetic claim diagnostics

## Objective

S4-2A fixes the MBP-10 non-proof gap by adding executable diagnostics for
queue-position mechanics, hidden-liquidity mechanics, and profitability
arithmetic. These diagnostics are synthetic only. They demonstrate that the
system can measure the mechanics under controlled assumptions, while explicitly
blocking real-market claims.

## Claim Boundary

| Area | What is now tested | What is still not claimed |
|---|---|---|
| Queue position | Synthetic queue-ahead depletion by trades and cancels, own-fill quantity, residual quantity, fill ratio, deterministic result hash. | Real queue position, exchange queue priority, order-level venue reconstruction. |
| Hidden liquidity | Synthetic displayed quantity, hidden quantity, replenishment clips, visible fill, hidden fill, residual quantity, fill ratio, deterministic result hash. | Real hidden liquidity, iceberg detection, implied liquidity, reserve-size inference. |
| Profitability | Synthetic gross PnL, fees, net PnL, average trade PnL, hit rate, max drawdown, deterministic result hash. | Strategy profitability, investment performance, production PnL, live execution quality. |

## Queue-Position Fixture Result

Input:

| Field | Value |
|---|---:|
| `order_id` | `queue_probe` |
| `symbol` | `CLM6` |
| `side` | `buy` |
| `order_quantity` | 20 |
| `initial_queue_ahead` | 15 |
| `events_processed` | 4 |

Events:

| Event | Quantity | Effect |
|---|---:|---|
| trade | 5 | Depletes queue ahead. |
| cancel | 4 | Depletes queue ahead without filling own order. |
| trade | 10 | Depletes remaining queue ahead and starts own fill. |
| trade | 16 | Completes own fill. |

Result:

| Metric | Result |
|---|---:|
| `final_queue_ahead` | 0 |
| `queue_ahead_depleted_by_trades` | 11 |
| `queue_ahead_depleted_by_cancels` | 4 |
| `filled_quantity` | 20 |
| `residual_quantity` | 0 |
| `fill_ratio` | 1.0 |
| `synthetic_queue_position_claimed` | true |
| `real_queue_position_claimed` | false |
| `errors` | 0 |
| `ok` | true |
| `result_hash` | `97fcd3bf8b1b7b3dcf8f89cf7be7ddd9c143a043dc39ca5d7ee56d376e5d3d7b` |

## Hidden-Liquidity Fixture Result

Input:

| Field | Value |
|---|---:|
| `order_id` | `hidden_probe` |
| `symbol` | `CLM6` |
| `side` | `buy` |
| `order_quantity` | 30 |
| `displayed_quantity` | 10 |
| `hidden_quantity` | 15 |
| `replenish_clip` | 5 |

Result:

| Metric | Result |
|---|---:|
| `visible_fill_quantity` | 10 |
| `hidden_fill_quantity` | 15 |
| `total_fill_quantity` | 25 |
| `residual_quantity` | 5 |
| `fill_ratio` | 0.8333333333 |
| `displayed_replenishments` | 3 |
| `hidden_liquidity_model_declared` | true |
| `real_hidden_liquidity_claimed` | false |
| `errors` | 0 |
| `ok` | true |
| `result_hash` | `11288b4c6eacc79d0c134ab91796db25d6e2fe5bb12bc72b582c4cb954a829b5` |

## Profitability Diagnostic Fixture Result

Input trades:

| Trade | Side | Quantity | Entry | Exit | Fees | Gross PnL | Net PnL |
|---|---|---:|---:|---:|---:|---:|---:|
| `buy_win` | buy | 10 | 75 | 76 | 1.00 | 10.00 | 9.00 |
| `sell_win` | sell | 5 | 80 | 78 | 0.50 | 10.00 | 9.50 |
| `buy_loss` | buy | 4 | 50 | 49 | 0.25 | -4.00 | -4.25 |

Aggregate result:

| Metric | Result |
|---|---:|
| `trades_total` | 3 |
| `winning_trades` | 2 |
| `losing_trades` | 1 |
| `gross_pnl` | 16 |
| `fees` | 1.75 |
| `net_pnl` | 14.25 |
| `average_trade_pnl` | 4.75 |
| `hit_rate` | 0.6666666667 |
| `max_drawdown` | 4.25 |
| `synthetic_profitability_claimed` | true |
| `real_profitability_claimed` | false |
| `errors` | 0 |
| `ok` | true |
| `result_hash` | `bb8a9c0e47617123eb4bf807c6fbb176a403d6e8b6d58437aaaee6df78747bc9` |

## Verification

- `uv run pytest tests/v2/s4_0/test_synthetic_claims.py -q` -> 8 passed
- `uv run pytest tests/v2/s4_0 -q` -> 38 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 273 passed

## Interpretation

This fixes the earlier ambiguity by making each disputed area executable and
explicitly bounded:

- Queue-position mechanics can be tested only as synthetic queue math unless
  an order-level venue feed and venue-specific priority semantics are present.
- Hidden-liquidity mechanics can be tested only as a declared synthetic model
  unless the system has evidence capable of proving reserve or iceberg behavior.
- Profitability can be calculated for synthetic fills, but those diagnostics do
  not prove alpha, tradability, live execution quality, or investment
  performance.
