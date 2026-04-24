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

## Deliberately Deferred

- Full MBO reconstructor.
- PCAP/raw-feed replay.
- Real/licensed CL front/next replay.
- Real/licensed tick/order-book replay.
- Any profitability or production-readiness claim.

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

## Interpretation

This closes the first executable slice of the reviewer feedback. It proves the
harness can test CL roll policy, replay ordering, lineage, and market-data depth
claim limits without waiting for licensed data. Formal S4 can proceed on
local/free or synthetic replay evidence, with source limitations recorded as
non-claims.
