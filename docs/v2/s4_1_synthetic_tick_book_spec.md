# S4-1 synthetic tick and order-book fixture specification

- **Status**: implemented fixture gate
- **Created**: 2026-04-24
- **Predecessor**: `s4_0_closeout.md`
- **Stage**: S4-1 synthetic microstructure fixture gate

## Objective

S4-1 proves that the system can validate synthetic tick-level ordering and
order-book fixture semantics without requiring real or licensed data.

## In Scope

- Deterministic synthetic tick event IDs.
- Same-timestamp multiple-event ordering.
- Sequence-gap detection.
- Missing-symbol segment detection.
- Top-of-book validation.
- MBP depth and monotonicity validation.
- Trade-price-within-book checks.
- Market-depth claim limits for trades, MBP-1, MBP-10, MBO, and PCAP.

## Out Of Scope

- Real or licensed market data.
- Full MBO order-level reconstruction.
- PCAP/raw-feed replay.
- Queue-position accuracy.
- Profitability or production-readiness claims.

## Minimum Pass Criteria

- Fixture source hash is deterministic across repeated evaluation.
- Expected symbol set is present.
- No unexplained SEV0/SEV1 replay-quality finding.
- Same-timestamp events preserve deterministic ordering.
- Book snapshots are not crossed.
- MBP levels are monotonic and within declared max depth.
- Fill claim is limited by declared market-data depth.
- MBO and PCAP remain explicitly unsupported until a later gate implements them.

## Exit Decision

S4-1 is complete when the executable fixture layer passes focused tests and the
PMO dashboard records the verification result.

## Current Verification

- `uv run pytest tests/v2/s4_0 -q` -> 25 passed
- `uv run ruff check v2/s4_0 tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 260 passed
