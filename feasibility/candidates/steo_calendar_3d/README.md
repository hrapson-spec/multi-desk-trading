# STEO Calendar -> WTI 3d Return Sign

Audit-only feasibility candidate for testing whether the EIA Short-Term Energy
Outlook release calendar contains directional WTI 3-day signal.

This candidate intentionally uses only the v1.0 PIT calendar payload. It does
not use STEO forecast table values because the current ingester does not parse
them yet. A forecast-value candidate requires a v1.1 table parser and a new
pre-registration.

Run:

```bash
.venv/bin/python feasibility/scripts/audit_steo_calendar_3d_phase3.py
```

