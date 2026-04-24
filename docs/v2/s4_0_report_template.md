# S4-0 post-run report template

- **Status**: template
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay

## 1. Executive Summary

- S4 objective.
- Run ID.
- Dates and instruments.
- Pass / conditional pass / fail.
- Major exceptions.

## 2. Scope and Assumptions

- What was in scope.
- What was out of scope.
- No-profitability statement.
- No-real-capital statement.
- Assumptions accepted before the run.

## 3. Data Sources

- Vendor.
- Dataset.
- Symbols.
- Live/delayed/replay status.
- Timestamp semantics.
- Licensing summary.
- Entitlement evidence.
- Unresolved licence caveats.

## 4. Architecture

- Feed capture.
- Normalization.
- Feature generation.
- Forecasting.
- Decisioning.
- Simulation.
- Monitoring.
- Storage/replay.

## 5. Controls Tested

- Data gaps.
- Stale features.
- Contract roll.
- Pre-trade simulation limits.
- Kill switch.
- Restore.
- Replay.
- Alerting.
- Manual override.

## 6. Run Metrics

- Declared sessions.
- Uptime.
- Data gaps.
- Duplicate records.
- Forecast count.
- Decision count.
- Abstention count.
- Simulated orders/fills.
- Incidents.
- Exceptions.

## 7. Incident Summary

- Incident table.
- Root causes.
- Severity.
- Status.
- Open mitigations.

## 8. Reconciliation Summary

- Raw to normalized.
- Forecast to decision.
- Decision to simulated order.
- Simulated fill to ledger.
- Ledger to daily summary.
- Unresolved reconciliation exceptions.

## 9. Replay and Restore Results

- Replay windows.
- Replay verification result.
- Divergence analysis.
- Restore drill outcome.
- Restored runtime counts.

## 10. Compliance and Boundary Notes

- No-money evidence.
- Data licence caveats.
- External communication restrictions.
- Items requiring legal or compliance review before later stages.

## 11. Stop/Go Assessment

- Green/amber/red result.
- Owner decisions required.
- Recommendation for next stage.
- Explicit non-claims.
