# S4-2B replay microstructure integration

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Predecessor**: `s4_2a_synthetic_claim_diagnostics.md`
- **Stage**: S4-2B replay evidence integration

## Objective

S4-2B integrates the MBP-10 synthetic fill drill and the synthetic
queue/hidden/PnL diagnostics into the recorded-replay evidence pack. The
purpose is to make microstructure claim boundaries part of every S4 replay
assessment rather than a detached standalone drill.

## Evidence Added To Replay Runs

The S4 recorded-replay runner now writes these files under `09_simulation/`:

| File | Purpose |
|---|---|
| `claim_boundary_report.json` | Source market-depth claim boundary and prohibited claims. |
| `mbp10_diagnostic_report.json` | Synthetic MBP-10 fill drill metrics and per-order results. |
| `synthetic_claim_diagnostics.json` | Synthetic queue-position, hidden-liquidity, and profitability diagnostics. |
| `microstructure_diagnostics_summary.json` | Aggregated status for replay manifest and CLI reporting. |

The run manifest now records:

- Source market depth.
- Claim boundary.
- Overall real-market non-claim flags.
- MBP-10 diagnostic report hash.

The final S4 report now includes:

- Source market depth.
- Synthetic MBP-10 fill ratio.
- Synthetic MBP-10 max depth consumed.
- Real queue-position, hidden-liquidity, profitability, and production-readiness claim flags.

## Local/Free Replay Verification

Command:

```bash
uv run python -m v2.governance.s4_0 --config data/s4_0/free_source_wti_futures/s4_0_local_free.yaml --overwrite
```

Result:

| Metric | Result |
|---|---:|
| `run_id` | `s4_0_wti_futures_yfinance_20251230_002` |
| `stop_go` | `green` |
| `family_decisions` | 20 |
| `execution_ledger` | 40 |
| `exceptions` | 0 |
| `source_market_depth` | `daily-continuous-front-futures-proxy` |
| `allowed_claim` | `source_limited_recorded_replay_only` |
| `mbp10_fill_ratio` | 0.4318181818 |
| `mbp10_max_depth_consumed` | 2 |
| `mbp10_report_hash` | `23cea64f09dc30d141195d72055abf5fc9b24dbd7338081ac31611dca9f89587` |
| `real_queue_position_claimed` | false |
| `real_hidden_liquidity_claimed` | false |
| `real_profitability_claimed` | false |
| `production_readiness_claimed` | false |

Because the source is a daily continuous futures proxy, the evidence pack
explicitly prohibits:

- Tick-level replay claims.
- Order-book replay claims.
- Queue-position accuracy claims.
- Hidden-liquidity inference claims.
- Real profitability claims.
- Production-readiness claims.

## Test Verification

- `uv run pytest tests/v2/s4_0/test_recorded_replay.py -q` -> 6 passed
- `uv run ruff check v2/s4_0/recorded_replay.py tests/v2/s4_0/test_recorded_replay.py` -> all checks passed
- `uv run pytest tests/v2/s4_0 -q` -> 38 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 273 passed

## Interpretation

This moves S4 from isolated microstructure drills to integrated replay evidence.
The system now records what its replay data can support, runs synthetic
microstructure diagnostics, and keeps real-market claims blocked unless a
future data source can support them.

This does not improve model alpha by itself. It improves the evidence harness
needed to assess, debug, and promote future ML trading decisions without
overclaiming the available data.
