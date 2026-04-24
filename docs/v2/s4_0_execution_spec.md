# S4-0 recorded replay execution specification

- **Status**: implementation baseline, tag `v2-s4-0-executor-0.1`
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay
- **Primary code target**: `v2/s4_0/recorded_replay.py`

## 1. Purpose

This slice turns S4-0 into an executable local recorded-replay runner. It does
not download Databento/CME data, does not store credentials, and no longer
requires real or licensed market data. The operator supplies a local/free or
synthetic replay CSV plus no-money run-control artefacts.

## 2. Execution Boundary

The runner can execute once these local inputs exist:

- Recorded replay CSV with `ts_event`, `symbol`, and `price`.
- Written owner approval and no-money attestation.
- Run config YAML declaring run ID, evidence root, symbols, session window, and
  decision interval.

The runner refuses to start if required run-control files are missing. It also
refuses pending templates: `owner_clearance_decision.md` must have the S4-0
approval checkbox checked, and `no_money_attestation.md` must have all no-money
attestations checked.

## 3. Command

```bash
uv run python -m v2.governance.s4_0 --config <path-to-s4_0.yaml>
```

Use `--overwrite` only to intentionally replace an existing evidence run root.

## 4. Required Run-Control Files

Place these in the configured `run_control_dir`:

- `owner_clearance_decision.md`
- `no_money_attestation.md`

Optional but recommended:

- `data_source_summary.md`
- `source_rights_note.md`
- `licence_boundary_table.md`
- `vendor_terms_summary.md`
- `exchange_route_summary.md`
- `reviewer_access_model.md`
- `unresolved_licence_questions.md`

## 5. Evidence Produced

The runner creates:

- run declaration and config snapshot
- copied run-control and data-source artefacts
- contract-selection receipt
- raw source manifest and optional raw copy
- normalized replay feed
- data-quality report
- forecast receipts
- decision receipts
- simulated execution ledger
- runtime control and incident logs
- uptime report
- reconciliation report
- replay verification report
- restore summary
- final S4-0 report
- `manifest.yaml` and `manifest.sha256`

## 6. Test Pack

```bash
uv run ruff check v2/s4_0 v2/governance/s4_0.py tests/v2/s4_0
uv run pytest tests/v2/s4_0 -q
uv run pytest tests/v2 -q
```
