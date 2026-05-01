# S4-0 licence clearance checklist

- **Status**: archived; no longer required for S4-0 execution
- **Created**: 2026-04-24
- **Superseded**: 2026-04-24 by local/free S4-0 scope decision
- **Stage**: S4-0 recorded replay

## 1. Current Position

S4-0 no longer requires real or licensed market data. This checklist is retained
only as an archive for a possible future commercial-data upgrade.

The current S4-0 gate requires:

- Local/free or synthetic recorded replay input.
- Source manifest and source limitations.
- Owner approval for a no-money run.
- Checked no-money attestation.
- Replay, restore, reconciliation, incident, and stop/go evidence.

## 2. Optional Future Use

If a future phase adds Databento, CME, dxFeed, Barchart, LSEG, or another
commercial source, create a separate data-licence review for that future scope.
That future review must not block the current S4-0 local/free replay phase.

## 3. Current Required Run-Control Files

Place these in the configured `run_control_dir`:

- `owner_clearance_decision.md`
- `no_money_attestation.md`

Optional context files:

- `data_source_summary.md`
- `source_rights_note.md`
- `licence_boundary_table.md`
- `vendor_terms_summary.md`
- `exchange_route_summary.md`
- `reviewer_access_model.md`
- `unresolved_licence_questions.md`
