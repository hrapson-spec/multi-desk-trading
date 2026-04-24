# Reliability sample assessment

- **Date**: 2026-04-24
- **Owner**: Henri Rapson
- **Assessment type**: partial reliability-gate sample
- **Full 4h gate status**: not completed
- **Outcome**: clean sample; no infrastructure incident detected

## 1. Context

The project PM dashboard had an open reliability-gate issue: the 4h wall-clock
soak runner existed, but the full operator-side 4h run had not been reconciled.

A fresh 4h run was started on 2026-04-24, then deliberately interrupted by
operator direction and assessed as a sample instead of a full gate pass.

## 2. Command

```bash
uv run scripts/run_soak_test.py \
  --db data/duckdb/soak_reliability_20260424.duckdb \
  --checkpoint-path data/soak/reliability_gate_20260424/checkpoint.pkl \
  --cadence-s 60 \
  --sample-interval-s 60 \
  --checkpoint-interval-s 600
```

## 3. Evidence Files

| Evidence | Path |
|---|---|
| DuckDB telemetry | `data/duckdb/soak_reliability_20260424.duckdb` |
| Soak log | `data/soak/reliability_gate_20260424/soak.log` |
| Checkpoint | `data/soak/reliability_gate_20260424/checkpoint.pkl` |

## 4. Sample Metrics

| Metric | Result |
|---|---:|
| Target duration | 14,400 seconds |
| Last logged elapsed | 5,104 seconds |
| Target completion | 35.4% |
| Decisions emitted | 86 |
| Forecast rows | 430 |
| Resource samples | 86 |
| Soak incidents | 0 |
| File descriptor range | 5 to 5 |
| RSS range | 38.09 MB to 132.77 MB |
| Last-sample RSS | 38.89 MB |
| DuckDB file size after stop | 4.3 MB |

The high RSS value occurred at the initial baseline sample. After warm-up, RSS
settled around 39 MB and stayed stable through the final samples.

## 5. Assessment

The sample is clean for the failure modes it exercised:

- no recorded soak incidents
- no file-descriptor growth
- no visible memory-growth pattern after warm-up
- checkpoint saved on interrupt
- forecast and decision writes continued through repeated cycles
- focused soak regression tests passed separately

Focused regression command:

```bash
uv run pytest tests/test_soak_checkpoint.py tests/test_soak_monitor.py tests/test_soak_incident.py tests/test_soak_runner_short.py -q
```

Result: `25 passed`.

## 6. Non-Claims

This assessment does not claim:

- the 4h reliability gate passed
- multi-hour or multi-day stability beyond the observed window
- live-feed reliability
- production uptime
- real-capital readiness

## 7. PM Disposition

Use this as a partial reliability sample for near-term assessment. Formal 4h
gate evidence remains available as a future rerun if the project needs to make
the exact §12.2 reliability-gate claim.
