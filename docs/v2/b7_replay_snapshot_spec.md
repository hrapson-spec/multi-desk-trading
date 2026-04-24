# B7 replay and snapshot verification specification

**Status**: implemented in workspace; awaiting acceptance tag  
**Created**: 2026-04-24  
**Slice**: v2 Phase B, immediately after B6b  
**Depends on**: B6b paper-live runtime receipts, deterministic runtime IDs  
**Primary code targets**: `v2/runtime/replay.py`, `v2/execution/simulator.py`

## 1. Purpose

B7 verifies that the B6b runtime receipt is still consistent with runtime
state. It is a hardening slice before any S4-style paper-live operational
claim.

B7 is intentionally smaller than the full restore procedure in
`kill_switch_and_rollback.md §6.2`. B6b writes lightweight receipts, not
full parquet snapshots. Therefore B7 proves receipt and runtime integrity;
it does not yet reconstruct a separate runtime database.

## 2. In Scope

- Load `runtime_root/snapshots/<decision_ts>/receipt.json`.
- Verify `receipt.sha256` over the exact receipt JSON content.
- Verify the receipt `decision_id` exists in `family_decisions`.
- Recompute `decision_hash` from stored `decision_json`.
- Recompute the decision ID from the decision hash.
- Recompute `kill_switch_hash` from stored `kill_switch_json`.
- Verify each receipt `execution_id` exists in `execution_ledger`.
- Recompute each execution hash from canonical ledger-row content.
- Recompute each execution ID from the execution hash.
- Compare `runtime_counts` against rows through the snapshot timestamp, not
  against current total rows after later ticks.
- Return structured checks rather than mutating runtime state.

## 3. Out of Scope

- Full restore into a fresh runtime DB.
- PIT manifest parquet snapshots.
- Position reconciliation against broker or external simulator state.
- `killctl` integration.
- Incident creation or alerting.
- S4 promotion evidence.

## 4. Acceptance Criteria

B7 is complete when:

- `verify_snapshot_receipt(...)` returns a structured pass/fail report.
- Valid B6b receipts verify successfully.
- Receipt tampering fails verification.
- Missing runtime rows fail verification.
- Runtime row hash drift fails verification.
- Receipts for earlier ticks still verify after later ticks append rows.
- Focused runtime/paper-live tests and full v2 tests pass.

## 5. Test Pack

```bash
uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q
uv run pytest tests/v2 -q
uv run ruff check v2/runtime v2/execution/simulator.py tests/v2/runtime
```
