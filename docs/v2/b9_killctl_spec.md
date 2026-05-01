# B9 killctl operator path specification

**Status**: accepted baseline, tag `v2-b9-killctl-0.1`  
**Created**: 2026-04-24  
**Slice**: v2 Phase B, immediately after B8  
**Depends on**: B6b kill-switch reader, B7/B8 runtime integrity checks  
**Primary code targets**: `v2/runtime/killctl.py`, `v2/governance/killctl.py`

## 1. Purpose

B9 adds the operator command path for runtime kill-switch changes. It turns
the B6b read-only `kill_switch.yaml` into an auditable operator-controlled
file backed by append-only incident events.

## 2. In Scope

- `isolate <family>/<desk>` adds the desk to `isolated_desks`.
- `freeze <family>` sets that family to `frozen`.
- `halt` sets system state to `halted`.
- `clear <family>/<desk>` removes one isolated desk.
- `clear <family>` restores the family to `enabled`, refusing while desks
  remain isolated.
- `clear system` restores system state to `enabled`.
- Every mutating command appends an event to `incidents.jsonl`.
- Every activation requires a reason and evidence path.
- Every clear requires an incident id and resolution evidence path.

## 3. Out of Scope

- Automated KS-* rule evaluation.
- External alerting.
- Formal post-incident review memo generation.
- Real broker flattening.

## 4. Acceptance Criteria

- Each operator command has a unit test.
- `load_kill_switch` reads killctl-generated YAML.
- Desk isolation affects the existing paper-live loop through B6b semantics.
- Family/system halts force paper-live hard-fail through existing B6b semantics.
- Clear refuses unsafe family clear while desks remain isolated.

## 5. Test Pack

```bash
uv run pytest tests/v2/runtime tests/v2/paper_live tests/v2/execution -q
uv run pytest tests/v2 -q
uv run ruff check v2/runtime v2/governance tests/v2/runtime
```
