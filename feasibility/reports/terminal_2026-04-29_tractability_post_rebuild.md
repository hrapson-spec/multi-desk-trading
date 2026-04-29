# Feasibility Harness v0 Report - Tractability Gate Post-Rebuild

Created: 2026-04-29
Git commit: `670fc1b3744d9e07959b719c165fd595aca71a7f`

## Verdict

- Rule: `continue_small_model_only`
- Action: `remove_foundation_models_from_harness`
- Minimum effective N: `163`

The rebuilt WPSR PIT spine produces enough post-2020 observations to continue,
but not enough to justify Chronos/Kronos/foundation-model branches. The harness
continues under the small-model-only constraint.

## Inputs

- PIT manifest: `data/pit_store/pit.duckdb`
- WPSR status: `ok`
- WPSR matched source: `eia`
- WPSR distinct usable timestamps: `327`
- Local archive manifest rows: `3948` true-first-release WPSR rows
- WTI path: `data/s4_0/free_source/raw/DCOILWTICO.csv`
- WTI proxy kind: `fred_wti_spot_proxy`
- WTI allowed use: `tractability_count_only`
- WTI forbidden uses: `executable_futures_replay`, `CL_front_month_backtest`,
  `MCL_execution_replay`

## Target Counts

| Target | Raw N | Effective N | Post-2020 effective N | Minimum detectable effect |
|---|---:|---:|---:|---:|
| 5d return sign | 326 | 163 | 163 | 10.72 percentage points |
| 5d return magnitude | 326 | 163 | 163 | 0.01204 absolute 5d log return |
| 5d MAE conditional on direction | 326 | 163 | 163 | 0.00471 absolute adverse 5d log return |

## Consequence

The rebuild changes the Phase 0.3 result from data-spine failure to a
statistically constrained continuation. Candidate audit may proceed only under
the pre-registered small-model-only path. Any document or architecture branch
that still routes Chronos-2 or Kronos into the harness is invalid for this run.
