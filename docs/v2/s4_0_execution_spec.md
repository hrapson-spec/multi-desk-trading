# S4-0 recorded replay execution specification

- **Status**: implementation baseline, tag `v2-s4-0-executor-0.1`
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay
- **Primary code target**: `v2/s4_0/recorded_replay.py`

## 1. Purpose

This slice turns the S4-0 research recommendation into an executable local
recorded-replay runner. It does not download Databento/CME data and does not
store credentials. The operator supplies a licensed local replay CSV and the
required written clearance artefacts.

## 2. Execution Boundary

The runner can execute once these local inputs exist:

- Databento-style recorded replay CSV with `ts_event`, `symbol`, and `price`.
- Written licence and no-money clearance files.
- Run config YAML declaring run ID, evidence root, symbols, session window, and
  decision interval.

The runner refuses to start if required clearance files are missing.
It also refuses pending templates: `owner_clearance_decision.md` must have the
S4-0 approval checkbox checked, and `no_money_attestation.md` must have all
no-money attestations checked.

## 3. Command

```bash
uv run python -m v2.governance.s4_0 --config <path-to-s4_0.yaml>
```

Use `--overwrite` only to intentionally replace an existing evidence run root.

## 4. Required Clearance Files

Place these in the configured `licence_clearance_dir`:

- `licence_boundary_table.md`
- `vendor_terms_summary.md`
- `owner_clearance_decision.md`
- `no_money_attestation.md`

Optional but recommended:

- `exchange_route_summary.md`
- `reviewer_access_model.md`
- `unresolved_licence_questions.md`

## 5. Evidence Produced

The runner creates:

- run declaration and config snapshot
- copied entitlement/no-money artefacts
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
