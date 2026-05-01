# B8 runtime restore specification

**Status**: accepted baseline, tag `v2-b8-runtime-restore-0.1`  
**Created**: 2026-04-24  
**Slice**: v2 Phase B, immediately after B7  
**Depends on**: B6b runtime DB, B7 receipt verification  
**Primary code targets**: `v2/runtime/restore.py`

## 1. Purpose

B8 restores a verified B6b/B7 runtime snapshot into a fresh runtime root.
This is the next operational hardening step before any S4-style paper-live
claim.

B8 still does not implement the full `kill_switch_and_rollback.md §6.2`
production restore procedure. It does not reconcile broker positions or PIT
manifest parquet snapshots, because B6b receipts do not yet contain those
artifacts. It proves that runtime decision/execution state can be reconstructed
through a verified receipt boundary.

## 2. In Scope

- Verify the source snapshot receipt with `verify_snapshot_receipt`.
- Refuse restore if source verification fails.
- Restore `family_decisions` rows through the snapshot timestamp.
- Restore `execution_ledger` rows through the snapshot timestamp.
- Copy snapshot receipt directories through the snapshot timestamp.
- Refuse non-empty target roots unless `overwrite=True`.
- Verify the restored runtime receipt after copying.
- Write a small `restore_report.json` in the target runtime root.

## 3. Out of Scope

- Broker or exchange reconciliation.
- PIT manifest parquet snapshot restore.
- Catch-up replay for vintages after the snapshot.
- `killctl` integration.
- Incident creation or alerting.
- S4 promotion evidence.

## 4. Acceptance Criteria

B8 is complete when:

- Valid source runtime state restores into a fresh runtime root.
- Restored runtime verifies with B7 receipt verification.
- Rows after the chosen snapshot are not copied.
- Tampered source receipts refuse restore.
- Non-empty target roots refuse restore unless overwrite is explicit.
- Focused runtime tests and full v2 tests pass.

## 5. Test Pack

```bash
uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q
uv run pytest tests/v2 -q
uv run ruff check v2/runtime tests/v2/runtime
```
