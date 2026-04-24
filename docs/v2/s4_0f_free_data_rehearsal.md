# S4-0F free-data operational rehearsal

- **Status**: executed green
- **Created**: 2026-04-24
- **Owner**: Henri Rapson
- **Stage**: S4-0F free-data operational rehearsal
- **Executor commit**: `08f95ce`
- **Formal S4-0 status**: accepted as the current S4-0 local/free-data evidence run

## 1. Scope Decision

S4-0 no longer requires real or licensed market data. The free-data run is
therefore treated as the current accepted S4-0 operating-model rehearsal, not
as a blocker-preserving downgrade. The evidence discipline remains unchanged:
the run still needs source hashes, normalized output, receipts, replay,
restore, reconciliation, incidents, and stop/go assessment.

S4-0F uses free/local daily WTI futures data to prove the operating machinery:
input manifesting, normalization, forecast receipts, decision receipts,
simulated ledger, incidents, replay verification, restore, and stop/go
reporting.

Real or licensed CL front/next replay may be added later as stronger evidence,
but it is no longer a requirement for this phase.

## 2. Input Data

| Field | Value |
|---|---|
| Source project | `/Users/henrirapson/projects/crude-oil-trader` |
| Source file | `data/raw/yfinance/wti_futures.parquet` |
| Derived replay file | `data/s4_0/free_source_wti_futures/raw/yfinance_wti_futures_replay.csv` |
| Symbol used | `CL_CONTINUOUS_YF` |
| Data shape | Daily continuous WTI futures OHLCV proxy; close used as replay price; volume used as size |
| Window | `2025-12-02T21:00:00Z` to `2025-12-30T21:00:00Z` |

## 3. Run Result

| Metric | Result |
|---|---:|
| Stop/go | green |
| Accepted replay rows | 20 |
| Decision count | 20 |
| Simulated execution ledger rows | 40 |
| Duplicate rows | 0 |
| Out-of-order rows | 0 |
| Replay windows verified | 20 |
| Restore outcome | passed |
| Exceptions | none |

Evidence root:

```text
data/s4_0/free_source_wti_futures/evidence/s4_0f_wti_futures_yfinance_20251230_001/
```

Key generated files:

- `manifest.yaml`
- `16_report/final_s4_0_report.md`
- `05_data_quality/data_quality_report.json`
- `14_replay/replay_verification_report.json`
- `15_restore/restore_summary.json`

## 4. Non-Claims

S4-0F does not prove:

- CL front/next contract replay.
- Tick-level or order-book processing.
- Contract-roll handling.
- Licensed-data handling.
- Live-feed timing behavior.
- Live execution quality.
- Profitability or investment performance.

## 5. Next Gate

The next gate is a repeatable S4-0 local/free replay run with the updated
runner contract in `docs/v2/s4_0_execution_spec.md`, then a one-week expansion
only if the one-session evidence pack remains green.
