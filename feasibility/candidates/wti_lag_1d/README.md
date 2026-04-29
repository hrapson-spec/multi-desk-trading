# WTI Lag -> WTI 1d Return Sign

Audit-only feasibility candidate for the post-3d pivot. The candidate tests
whether a strict previous-trading-day WTI lag predicts the next one-day WTI
return sign on the all-calendar event stream.

This is not a production desk and is not promotion-ready by itself: the
candidate was identified after the 3d candidate set failed, so the historical
pass is an exploratory success. Promotion requires a forward lock and rerun.

Run:

```bash
.venv/bin/python feasibility/scripts/audit_wti_lag_1d_phase3.py
```

