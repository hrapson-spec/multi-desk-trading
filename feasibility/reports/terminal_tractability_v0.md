# Feasibility Harness v0 Terminal Report — Tractability Gate

Created: 2026-04-29T06:31:07.935079Z
Git commit: `b4c5d83e30105fadf70d2cb4980d78eb46122844`

## Verdict

- Rule: `stop`
- Action: `write_terminal_report_do_not_build_harness`
- Minimum effective N: `0`

The harness stops at Phase 0.3. No modelling code should be written for this track until the PIT WPSR data spine exists and the tractability calculation is re-run.

## Blocking Finding

- WPSR input status: `missing_pit_manifest`
- PIT manifest path: `data/pit_store/pit.duckdb`
- Matched WPSR manifest rows: `0`
- WTI input status: local proxy present with `20` rows from `2025-12-02T21:00:00+00:00` to `2025-12-30T21:00:00+00:00`

This is a data-spine failure, not a model failure. It is a successful feasibility outcome because it prevents spending weeks on an underpowered or non-existent sample.
