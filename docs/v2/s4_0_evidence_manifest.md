# S4-0 evidence manifest

- **Status**: research-informed planning baseline, tag `v2-s4-0-research-0.1`
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay

## 1. Purpose

This manifest defines the evidence pack required for the S4-0 recorded replay
dry run. An independent reviewer should be able to trace selected events from
raw replay input to normalized input, feature generation, forecast, decision,
simulated execution, ledger, incident status, replay result, restore result,
and final run assessment.

## 2. Evidence Root

Use a dedicated run root:

```text
evidence/s4_0/<run_id>/
```

The run ID should encode the stage, instrument family, session date, and a
short sequence number, for example:

```text
s4_0_wti_20260504_001
```

## 3. Required Folder Structure

```text
evidence/s4_0/<run_id>/
  00_run_control/
  01_entitlements/
  02_reference_data/
  03_raw_feed/
  04_normalized_feed/
  05_data_quality/
  06_features/
  07_forecasts/
  08_decisions/
  09_simulation/
  10_runtime_controls/
  11_incidents/
  12_monitoring/
  13_reconciliation/
  14_replay/
  15_restore/
  16_report/
  manifest.yaml
  manifest.sha256
```

## 4. Required Evidence Classes

| Folder | Required evidence |
|---|---|
| `00_run_control/` | Run declaration, session calendar, code commit, config snapshot, stop/go criteria. |
| `01_entitlements/` | Data-source selection record, licence summary, entitlement evidence, unresolved caveats. |
| `02_reference_data/` | Instrument map, front/next mapping, contract-roll rule, trading session definition. |
| `03_raw_feed/` | Raw replay files or raw API capture, source hashes, source metadata. |
| `04_normalized_feed/` | Normalized events or bars, schema version, normalization log. |
| `05_data_quality/` | Gap report, duplicate report, timestamp report, stale-feature report. |
| `06_features/` | Feature outputs, PIT metadata, feature manifest. |
| `07_forecasts/` | Forecast records, forecast receipts, forecast exception log. |
| `08_decisions/` | Decision receipts, abstention receipts, family synthesis records. |
| `09_simulation/` | Simulated orders, simulated fills, execution ledger, daily summary. |
| `10_runtime_controls/` | Kill-switch state changes, manual override log, operator actions. |
| `11_incidents/` | Incident log, closure evidence, root-cause notes, open mitigations. |
| `12_monitoring/` | Uptime report, alert log, process health records. |
| `13_reconciliation/` | Raw-to-normalized, forecast-to-decision, decision-to-order, fill-to-ledger checks. |
| `14_replay/` | Replay windows, verification report, divergence analysis. |
| `15_restore/` | Restore drill input, restore report, restored runtime counts. |
| `16_report/` | Final S4-0 report, stop/go assessment, owner sign-off. |

## 5. Manifest File Requirements

`manifest.yaml` must include:

- Run ID.
- Stage.
- Instrument family.
- Session date and window.
- Data source.
- Dataset identifiers.
- Code commit.
- Config hash.
- Evidence file list.
- SHA-256 hash for each evidence file.
- Record counts by evidence class.
- Known exceptions.
- Owner sign-off status.

## 6. Reconciliation Trace

For sampled events, the evidence pack must support this path:

```text
raw feed event
  -> normalized event
  -> feature row
  -> forecast record
  -> forecast receipt
  -> decision receipt
  -> simulated order
  -> simulated fill
  -> execution ledger row
  -> daily summary
```

If the system abstains, the trace must show:

```text
raw feed event
  -> normalized event
  -> feature row
  -> forecast or blocked forecast state
  -> abstention receipt
  -> no simulated order
  -> ledger or daily summary abstention count
```

## 7. Minimum Completion Standard

The run is not assessable unless:

- `manifest.yaml` exists.
- All required folders exist.
- Required evidence classes are either populated or explicitly marked
  not-applicable with a reason.
- All evidence files have hashes.
- Reconciliation samples are present.
- Replay and restore reports exist.
- Stop/go assessment is signed or explicitly left unsigned with a blocker.
