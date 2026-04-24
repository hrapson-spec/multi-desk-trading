# S4 test execution status

- **Status**: executable test layer started
- **Created**: 2026-04-24
- **Scope**: tests for local/free or synthetic S4 replay data
- **Formal S4 status**: no longer blocked on licensed or real data

## Implemented Now

| Area | Implementation | Evidence |
|---|---|---|
| CL front/next definition | `v2/s4_0/contract_roll.py` | `tests/v2/s4_0/test_contract_roll.py` |
| Roll policy | Pre-expiry no-new-trades and must-flat windows | `ROLL_001`-style fixture coverage in `test_contract_roll.py` |
| Holiday-adjusted last trade date | CL last-trade-date helper with exchange holiday fixture | `test_cl_last_trade_date_adjusts_holiday_25th_anchor` |
| Synthetic front/next replay invariants | Runner now emits timestamp audit and source-to-decision lineage evidence | `tests/v2/s4_0/test_recorded_replay.py` |
| Tick ordering and gap semantics | `v2/s4_0/replay_quality.py` | `tests/v2/s4_0/test_replay_quality.py` |
| Same-timestamp events | Deterministic ordering policy tests | `test_same_timestamp_multiple_events_are_reported_without_reordering` |
| Sequence gaps vs time gaps | Material sequence gaps separated from no-trade style time gaps | `test_sequence_gap_is_material_sev1`, `test_time_gap_without_sequence_break_is_not_the_same_as_sequence_gap` |
| Market-data depth / fill-claim limits | `v2/s4_0/market_data.py` | `tests/v2/s4_0/test_market_data.py` |
| Order-book overclaim control | MBP-10 cannot claim queue-position accuracy; MBO required for order-level queue claims | `test_fill_claim_limits_prevent_overclaiming_queue_accuracy_on_mbp10` |
| Synthetic tick/book fixture gate | `v2/s4_0/synthetic_microstructure.py` | `tests/v2/s4_0/test_synthetic_microstructure.py` |
| MBP-10 simulated-fill drill | `v2/s4_0/mbp10_fill.py` | `tests/v2/s4_0/test_mbp10_fill.py` |
| Synthetic queue/hidden/PnL diagnostics | `v2/s4_0/synthetic_claims.py` | `tests/v2/s4_0/test_synthetic_claims.py` |
| Replay-integrated microstructure evidence | S4 replay now writes claim-boundary, MBP-10, queue/hidden/PnL diagnostic reports into `09_simulation/` | `tests/v2/s4_0/test_recorded_replay.py` |
| Local/free WTI model-quality diagnostic | PIT-safe ridge walk-forward over FRED WTI spot proxy versus empirical and zero-Gaussian baselines | `tests/v2/s4_0/test_model_quality.py` |

## Deliberately Deferred

- Full MBO reconstructor beyond explicit deferral checks.
- PCAP/raw-feed replay beyond explicit deferral checks.
- Real/licensed CL front/next replay.
- Real/licensed tick/order-book replay.
- Any real profitability or production-readiness claim.

## Verification

```bash
uv run pytest tests/v2/s4_0 -q
uv run ruff check v2/s4_0 tests/v2/s4_0
uv run pytest tests/v2 -q
```

Latest result:

- `tests/v2/s4_0`: 19 passed
- `ruff`: all checks passed
- `tests/v2`: 254 passed
- `tests/v2/s4_0`: 20 passed after removing the licensed-data gate
- `tests/v2`: 255 passed after removing the licensed-data gate
- `s4_0_wti_futures_yfinance_20251230_002`: green local/free S4-0 rerun
- `s4_0c_wti_futures_yfinance_week_20251219_001`: green one-week local/free expansion
- S4-1 synthetic tick/book fixture tests added for deterministic hashes, sequence gaps, top-of-book/MBP validation, and MBO deferral.
- `tests/v2/s4_0`: 25 passed after S4-1 fixture gate
- `ruff`: all checks passed after S4-1 fixture gate
- `tests/v2`: 260 passed after S4-1 fixture gate
- S4-2 MBP-10 fill drill: OK; 4 orders, 57/132 quantity filled, fill ratio 0.4318181818, max depth 2, queue position not claimed.
- `tests/v2/s4_0`: 30 passed after S4-2 fill drill
- `ruff`: all checks passed after S4-2 fill drill
- `tests/v2`: 265 passed after S4-2 fill drill
- S4-2A synthetic claim diagnostics: queue-position, hidden-liquidity, and profitability mechanics tested under synthetic assumptions; real queue, real hidden-liquidity, and real profitability claims all false by construction.
- `tests/v2/s4_0/test_synthetic_claims.py`: 8 passed after S4-2A diagnostic layer
- `tests/v2/s4_0`: 38 passed after S4-2A diagnostic layer
- `ruff`: all checks passed after S4-2A diagnostic layer
- `tests/v2`: 273 passed after S4-2A diagnostic layer
- S4-2B replay integration: local/free replay green with integrated microstructure diagnostics; 20 family decisions, 40 execution ledger rows, 0 exceptions, source depth `daily-continuous-front-futures-proxy`, MBP-10 diagnostic fill ratio 0.4318181818, real queue/hidden/profitability/production-readiness claims false.
- `tests/v2/s4_0/test_recorded_replay.py`: 6 passed after S4-2B integration
- `tests/v2/s4_0`: 38 passed after S4-2B integration
- `ruff`: all checks passed after S4-2B integration
- `tests/v2`: 273 passed after S4-2B integration
- S4-3 model-quality diagnostic: 9,381 walk-forward decisions on FRED WTI spot proxy; simple ridge not promotable; pinball improvements -1.54% versus empirical and -0.66% versus zero-Gaussian; directional accuracy 50.77%.
- `tests/v2/s4_0/test_model_quality.py`: 4 passed after S4-3 diagnostic
- `tests/v2/s4_0`: 42 passed after S4-3 diagnostic
- `ruff`: all checks passed after S4-3 diagnostic
- `tests/v2`: 277 passed after S4-3 diagnostic

## Interpretation

This closes the first executable slice of the reviewer feedback. It proves the
harness can test CL roll policy, replay ordering, lineage, and market-data depth
claim limits without waiting for licensed data. Formal S4 can proceed on
local/free or synthetic replay evidence, with source limitations recorded as
non-claims.

The local/free recorded replay gate has now run twice under the revised scope:
a current-scope full-window rerun and an explicit one-week expansion. Both were
green.

S4-1 now has an executable synthetic fixture layer. It validates tick ordering
and order-book fixture semantics without claiming real book reconstruction.

S4-2 now has an executable MBP-10 simulated-fill drill. It validates
depth-aware synthetic fills, partial fills, limit constraints, aggregate
metrics, and the queue-position non-claim.

S4-2A now has explicit synthetic diagnostics for queue-position mechanics,
hidden-liquidity mechanics, and profitability arithmetic. This adds measurable
coverage for the disputed areas without converting them into real-market
claims.

S4-2B integrates those diagnostics into recorded-replay evidence packs. Each
run now emits a claim-boundary report, MBP-10 diagnostic report, synthetic
claim diagnostics, and a manifest-level summary.

S4-3 adds the first local/free WTI model-quality diagnostic. The current simple
ridge signal fails promotion against conservative baselines, so the next work
must improve signal inputs rather than advance production-readiness claims.
