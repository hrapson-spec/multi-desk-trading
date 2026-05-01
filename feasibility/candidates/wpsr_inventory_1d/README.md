# wpsr_inventory_1d - Audit-Only Feasibility Candidate

## Positioning: NOT a Production Desk

This module is an **audit-only feasibility candidate**. It does **not** implement
`desks.base.DeskProtocol` and is **not registered on the bus**.

The target is `wti_front_1d_return_sign`, a sign target. The v1 controller
combines desk outputs in log-return units, so this candidate remains outside
`desks/` unless a future promotion review defines a compatible decision unit.

## Pre-registration

Pre-reg: `feasibility/preregs/2026-05-01-wpsr_inventory_wti_1d.yaml`

## Claim

The primary claim is WPSR-only: it intentionally excludes WTI lag features. The
features are PIT-safe trailing weekly-change z-scores for crude stocks, Cushing
stocks, gasoline-plus-distillate stocks, refinery utilization, crude production,
net imports, and products supplied.

## How to Run the Audit

```bash
.venv/bin/python feasibility/scripts/audit_wpsr_inventory_1d_phase3.py
```

The script builds PIT-safe WPSR release-time features, fits a monthly
expanding-window logistic model, writes residuals, and invokes the tractability
harness in Phase 3 residual mode.

## Candidate Outputs

Residuals CSV: `feasibility/outputs/wpsr_inventory_1d_residuals.csv`

Columns:
- `decision_ts` (UTC DatetimeIndex)
- `residual` (values in {-2, 0, +2}; computed as `y_true_sign - y_pred_sign`)
