# B10 Phase B dry-run closeout specification

**Status**: accepted baseline, tag `v2-b10-phase-b-dry-run-0.1`
**Created**: 2026-04-24
**Slice**: v2 Phase B closeout
**Depends on**: B6b paper-live loop, B7 receipt verification, B8 restore, B9 killctl
**Primary code target**: `v2/runtime/dry_run.py`

## 1. Purpose

B10 closes the Phase B operational substrate by running a deterministic
no-capital dry-run over the runtime components that would be load-bearing
for S4 shadow-live later.

This is not an S4 promotion. It is a CI/local operational drill proving that
the substrate components compose.

## 2. In Scope

- Run a normal enabled paper-live tick.
- Verify the enabled tick receipt.
- Use `killctl isolate` to isolate the dry-run desk.
- Run a tick with no active desks and verify abstention receipt.
- Clear the desk isolation.
- Use `killctl freeze` to freeze the family.
- Run a frozen tick and verify hard-fail receipt.
- Clear the family freeze.
- Restore the first snapshot into a fresh runtime root.
- Return a structured dry-run report.

## 3. Out of Scope

- Live feeds.
- Broker/exchange connection.
- Real desk promotion evidence.
- S4 operational evidence pack.
- External alerting.

## 4. Acceptance Criteria

- Dry-run report returns `ok=True`.
- Runtime ledger contains three decisions and six execution rows.
- Restored runtime contains the first snapshot only.
- Incident log contains isolation and freeze incidents plus closure events.
- Focused runtime/paper-live/execution tests and full v2 tests pass.

## 5. Test Pack

```bash
uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q
uv run pytest tests/v2 -q
uv run ruff check v2/runtime v2/governance tests/v2/runtime
```
