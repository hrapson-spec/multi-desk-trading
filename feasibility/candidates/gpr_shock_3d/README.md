# gpr_shock_3d — Audit-Only Feasibility Candidate

## Positioning: NOT a Production Desk

This module is an **audit-only feasibility candidate**. It does **not** implement
`desks.base.DeskProtocol` and is **not registered on the bus**.

The target is `wti_front_3d_return_sign`, a sign target. The v1 controller combines
desk outputs in log-return units, so this candidate remains outside `desks/` unless a
future promotion review defines a compatible decision unit.

## Pre-registration

Pre-reg: `feasibility/preregs/2026-04-29-gpr_shock_wti_3d.yaml`

## How to Run the Audit

```bash
.venv/bin/python feasibility/scripts/audit_gpr_shock_3d_phase3.py
```

The script fetches the public Caldara-Iacoviello daily recent GPR data snapshot,
aligns it to the existing GPR weekly PIT calendar, fits a rolling-origin logistic
model, writes residuals, and invokes the tractability harness in Phase 3 residual
mode. The value source is current-snapshot public data, not true PIT vintages.

