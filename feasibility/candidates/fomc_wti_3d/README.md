# fomc_wti_3d — Audit-Only Feasibility Candidate

## Positioning: NOT a Production Desk

This module is an **audit-only feasibility candidate**. It does **not** implement
`desks.base.DeskProtocol` and is **not registered on the bus**.

### Why not a desk?

The v1 Controller at `controller/decision.py:94` raw-sums `weight × point_estimate` across
all desks. The oil desk family emits `WTI_FRONT_1W_LOG_RETURN` (log-return targets). This
candidate's output target is `wti_front_3d_return_sign` — a sign (±1) target — which cannot
be mixed with log-return units in the controller's weighted sum without introducing a
decision-unit collision. Emitting sign values into the controller sum would silently corrupt
the combined signal.

Therefore this candidate lives under `feasibility/candidates/` and is evaluated offline only.

## Pre-registration

Pre-reg: `feasibility/preregs/2026-04-29-fomc_wti_3d.yaml`

## How to Run the Audit

The audit harness is invoked via:

```bash
.venv/bin/python feasibility/scripts/audit_fomc_3d_phase3.py --phase3-residual-mode
```

This script runs the harness in `--phase3-residual-mode`, fitting the
`LogisticRegressionFeasibilityModel` on the train split and computing residuals on the
test split.

## Candidate Outputs

Residuals CSV: `feasibility/outputs/fomc_3d_residuals.csv`

Columns:
- `decision_ts` (UTC DatetimeIndex)
- `residual` (values in {-2, 0, +2}; computed as `y_true_sign - y_pred_sign`)

## Module

`feasibility/candidates/fomc_wti_3d/classical.py` — `LogisticRegressionFeasibilityModel`
