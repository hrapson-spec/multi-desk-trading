# wpsr_inventory_3d — Audit-Only Feasibility Candidate

## Positioning: NOT a Production Desk

This module is an **audit-only feasibility candidate**. It does **not** implement
`desks.base.DeskProtocol` and is **not registered on the bus**.

The target is `wti_front_3d_return_sign`, a sign target. The v1 controller combines
desk outputs in log-return units, so this candidate remains outside `desks/` unless a
future promotion review defines a compatible decision unit.

## Pre-registration

Pre-reg: `feasibility/preregs/2026-04-29-wpsr_inventory_wti_3d.yaml`

## How to Run the Audit

```bash
.venv/bin/python feasibility/scripts/audit_wpsr_inventory_3d_phase3.py
```

The script builds PIT-safe WPSR release-time features, fits a rolling-origin logistic
model, writes residuals, and invokes the tractability harness in Phase 3 residual mode.

## Candidate Outputs

Residuals CSV: `feasibility/outputs/wpsr_inventory_3d_residuals.csv`

Columns:
- `decision_ts` (UTC DatetimeIndex)
- `residual` (values in {-2, 0, +2}; computed as `y_true_sign - y_pred_sign`)

