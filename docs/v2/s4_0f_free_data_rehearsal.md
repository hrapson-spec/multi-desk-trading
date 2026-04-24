# S4-0F free-data operational rehearsal

- **Status**: executed green
- **Created**: 2026-04-24
- **Owner**: Henri Rapson
- **Stage**: S4-0F free-data operational rehearsal
- **Executor commit**: `08f95ce`
- **Formal S4-0 status**: still blocked on licensed CL front/next recorded replay data

## 1. Downgrade Decision

S4-0F is a scope downgrade from formal S4-0, not a downgrade in evidence
discipline. It exists because the workspace does not currently contain licensed
CL front/next tick or book replay data. The local Databento placeholder file is
only a header row.

S4-0F uses free/local daily WTI futures data to prove the operating machinery:
input manifesting, normalization, forecast receipts, decision receipts,
simulated ledger, incidents, replay verification, restore, and stop/go
reporting.

Formal S4-0 remains reserved for a reviewer-grade CL front/next recorded replay
run with clear data rights.

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
- CME/Databento licence clearance.
- Live-feed timing behavior.
- Live execution quality.
- Profitability or investment performance.

## 5. Next Gate

The next formal gate is unchanged: obtain licensed CL front/next recorded replay
data and written clearance for non-display use, local storage, local replay,
retention, and reviewer access. Once that exists, run formal S4-0 using
`docs/v2/s4_0_execution_spec.md`.
