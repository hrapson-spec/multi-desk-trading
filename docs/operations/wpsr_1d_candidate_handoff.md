# WPSR 1d Surprise Candidate Handoff

Date: 2026-05-01  
Repo: `/Users/henrirapson/projects/multi-desk-trading`  
Branch context: local feasibility branch; do not assume anything has been pushed.

## Objective

Build and audit one new value-bearing WPSR candidate:

> WPSR inventory/supply surprise features -> `wti_front_1d_return_sign`

The candidate must use only information available before each WPSR decision
timestamp, run through the existing walk-forward + residual-mode Phase 3
harness, and explicitly test whether it beats the majority-sign baseline.

The point is not to create another broad "find alpha" branch. The point is to
answer one narrow question:

> Can a causal WPSR value feature beat the current weak lag-only signal on WTI
> 1-day return sign without leakage?

## Current State

The codebase already has:

- Historical WPSR first-release PIT values in the PIT store.
- A working WTI/FRED spot proxy refresh path.
- A locked, automated forward-evidence loop for the current 1d WTI lag
  candidate.
- A prior WPSR inventory candidate for the 3d target, which failed Phase 3.

Do not reinvent those pieces.

## Do Not Modify These Locked Files

The current live forward candidate is locked in:

- `feasibility/forward/wti_lag_1d/lock.json`
- `feasibility/candidates/wti_lag_1d/classical.py`
- `feasibility/scripts/audit_wti_lag_1d_phase3.py`
- `feasibility/preregs/2026-04-29-wti_lag_all_calendar_1d.yaml`
- `feasibility/outputs/tractability_v1_1d_phase3_audit_wti_lag.json`
- `feasibility/outputs/wti_lag_1d_residuals.csv`
- `feasibility/tractability_v1.py`
- `contracts/target_variables.py`

The lock pins exact SHA256 hashes. Editing any pinned file can break the daily
forward pipeline's lock-integrity check. If a harness change becomes truly
necessary, stop and document a re-lock plan separately. The preferred path for
this task is additive new files only.

Verify the lock before and after:

```bash
cd /Users/henrirapson/projects/multi-desk-trading
.venv/bin/python - <<'PY'
from feasibility.scripts.forward_wti_lag_1d import verify_forecast_chain, verify_lock_integrity
print(verify_lock_integrity())
print(verify_forecast_chain())
PY
```

Expected shape:

```text
{'status': 'ok', 'lock_id': 'dcc249c4d25a8890', 'checked_files': 7}
{'status': 'ok', 'forecast_count': ...}
```

## Current Locked Baseline To Beat

Locked candidate:

- Candidate id: `wti_lag_all_calendar_1d_audit_candidate`
- Target: `wti_front_1d_return_sign`
- Horizon/purge/embargo: `1/1/1`
- Families: `wpsr,fomc,steo,opec_ministerial,psm,gpr`
- Feature: strict previous-trading-day WTI 1d log return
- Model: logistic regression, `C=0.25`

Historical Phase 3 metrics from `feasibility/forward/wti_lag_1d/lock.json`:

| Metric | Value |
| --- | ---: |
| n_after_purge_embargo | 648 |
| scored_residuals | 589 |
| HAC effective N | 524 |
| block-bootstrap effective N | 547 |
| model_accuracy | 52.12% |
| zero_return_baseline_accuracy | 47.03% |
| majority_baseline_accuracy | 52.97% |
| gain_vs_zero_return_baseline | +5.09 pp |
| gain_vs_majority_baseline | -0.85 pp |

The known weakness is the majority baseline. A new candidate that only beats
zero but still loses to majority does not solve the problem.

## Existing WPSR 3d Candidate To Reuse

Prior candidate files:

- `feasibility/candidates/wpsr_inventory_3d/classical.py`
- `feasibility/scripts/audit_wpsr_inventory_3d_phase3.py`
- `feasibility/preregs/2026-04-29-wpsr_inventory_wti_3d.yaml`
- `feasibility/reports/terminal_2026-04-29_phase3_audit_wpsr_inventory.md`
- `feasibility/outputs/wpsr_inventory_3d_residuals.csv`
- `feasibility/outputs/tractability_v1_3d_phase3_audit_wpsr_inventory.json`

Prior 3d result:

| Metric | Value |
| --- | ---: |
| target | `wti_front_3d_return_sign` |
| family | `wpsr` |
| horizon/purge/embargo | `3/3/3` |
| n_after_purge_embargo | 272 |
| scored_events | 227 |
| model_accuracy | 50.22% |
| zero_return_baseline_accuracy | 43.61% |
| majority_baseline_accuracy | 56.39% |
| gain_vs_zero_return_baseline | +6.61 pp |
| HAC effective N | 176 |
| block-bootstrap effective N | 175 |
| verdict | NON-ADMISSIBLE |

Interpretation: the 3d WPSR value candidate beat the zero baseline but failed
the majority baseline and residual effective-N gates. The next attempt should
adapt the value-bearing WPSR machinery to the 1d target and avoid repeating the
same report with only labels changed.

## WPSR Data Already Available

Historical first-release WPSR archive ingester:

- `v2/ingest/eia_wpsr_archive.py`
- Tests: `tests/v2/ingest/test_eia_wpsr_archive.py`
- Pre-2020 tests: `tests/v2/ingest/test_eia_wpsr_archive_pre_2020.py`

Current/latest EIA series API ingester:

- `v2/ingest/eia_wpsr.py`
- Test: `tests/v2/ingest/test_eia_wpsr_fetcher.py`

Important distinction:

- `eia_wpsr_archive.py` restores true first-release archive table values.
- `eia_wpsr.py` uses the EIA series API and marks data as latest snapshot, not
  true PIT history.

For historical audit, prefer archive PIT values. Do not use current revised EIA
history where first-release archive values exist.

Useful WPSR series in `eia_wpsr_archive.py`:

| Series | Meaning |
| --- | --- |
| `WCESTUS1` | Commercial crude inventories excluding SPR |
| `WCSSTUS1` | SPR |
| `W_EPC0_SAX_YCUOK_MBBL` | Cushing crude stocks |
| `WGTSTUS1` | Total motor gasoline inventories |
| `WDISTUS1` | Distillate fuel oil inventories |
| `WKJSTUS1` | Kerosene-type jet fuel inventories |
| `WPRSTUS1` | Propane/propylene inventories |
| `WCRFPUS2` | Domestic crude production |
| `WCRIMUS2` | Crude imports |
| `WCREXUS2` | Crude exports |
| `WRPUPUS2` | Products supplied |
| `WPULEUS3` | Refinery utilization |

The existing 3d candidate uses this required subset:

```python
REQUIRED_WPSR_SERIES = (
    "WCESTUS1",
    "WGTSTUS1",
    "WDISTUS1",
    "WPULEUS3",
    "WCRIMUS2",
    "WCREXUS2",
)
```

It builds these features:

- `crude_stock_change_z`
- `product_stock_change_z`
- `refinery_utilization_change_z`
- `net_import_change_z`

Each feature uses the current release's week-over-week change and normalizes
against prior releases only. That is PIT-safe if the panel is indexed by the
release timestamp and rolling statistics are shifted by one release before
normalization.

Consider whether the 1d candidate should also add `cushing_stock_change_z` from
`W_EPC0_SAX_YCUOK_MBBL`; if so, pre-register it before evaluating. Do not run a
feature-shopping loop and then backfill the prereg.

Inspect PIT availability:

```bash
.venv/bin/python - <<'PY'
import duckdb
conn = duckdb.connect("data/pit_store/pit.duckdb", read_only=True)
rows = conn.execute("""
    SELECT source, dataset, series, COUNT(*) AS n,
           MIN(usable_after_ts), MAX(usable_after_ts)
    FROM pit_manifest
    WHERE dataset = 'wpsr'
    GROUP BY source, dataset, series
    ORDER BY series
""").fetchall()
for row in rows:
    print(row)
PY
```

## Price Data And Target Rules

WTI price proxy:

- File: `data/s4_0/free_source/raw/DCOILWTICO.csv`
- Refresh script: `feasibility/scripts/refresh_wti_spot_proxy.py`
- Forward refresh status:
  `feasibility/forward/wti_lag_1d/wti_spot_refresh_status.json`

The daily WTI proxy is date-stamped, not intraday-vintaged. For event-time
features, use only values available before the event's UTC calendar day. Reuse:

- `strict_previous_trading_day_log_return()` in
  `feasibility/candidates/wti_lag_1d/classical.py`

Do not use the event-day daily price as a feature for a Wednesday 10:35 ET WPSR
decision. The event-day close is not known yet.

Target variable:

- `wti_front_1d_return_sign` from `contracts/target_variables.py`
- Harness target name used in manifests: `wti_1d_return_sign`
- Metric: `return_sign`

## Harness Surfaces To Use

Main harness:

- `feasibility/tractability_v1.py`

Relevant APIs:

- `WPSR_FAMILY`
- `DEFAULT_PIT_ROOT`
- `DEFAULT_WTI_PATHS`
- `POST_2020_START`
- `TargetDef`
- `TargetObservation`
- `load_family_decision_events()`
- `load_target_prices()`
- `build_target_observations()`
- `kept_decision_ts()`

Residual-mode CLI shape for this candidate:

```bash
.venv/bin/python -m feasibility.tractability_v1 \
  --families wpsr \
  --horizon-days 1 \
  --purge-days 1 \
  --embargo-days 1 \
  --phase3-residual-mode \
  --candidate-residuals-csv feasibility/outputs/wpsr_inventory_1d_residuals.csv \
  --output feasibility/outputs/tractability_v1_1d_phase3_audit_wpsr_inventory.json
```

Residual CSV schema:

```csv
decision_ts,residual
2020-01-08T15:35:00Z,0.0
...
```

Residual values should be `y_true_sign - y_pred_sign`, where signs are in
`{-1, +1}`.

## Recommended New Files

Use additive names. Do not overwrite the 3d candidate.

Candidate package:

- `feasibility/candidates/wpsr_inventory_1d/__init__.py`
- `feasibility/candidates/wpsr_inventory_1d/classical.py`
- `feasibility/candidates/wpsr_inventory_1d/README.md`

Pre-registration:

- `feasibility/preregs/2026-05-01-wpsr_inventory_wti_1d.yaml`

Audit script:

- `feasibility/scripts/audit_wpsr_inventory_1d_phase3.py`

Outputs:

- `feasibility/outputs/wpsr_inventory_1d_residuals.csv`
- `feasibility/outputs/tractability_v1_1d_phase3_audit_wpsr_inventory.json`

Report:

- `feasibility/reports/terminal_2026-05-01_phase3_audit_wpsr_inventory_1d.md`

Tests:

- `tests/feasibility/candidates/test_wpsr_inventory_1d.py`

## Suggested Candidate Specification

Start with one pre-registered model. If testing multiple variants, create
separate preregs before looking at results.

Primary version:

- Target: `wti_front_1d_return_sign`
- Family: `wpsr`
- Horizon/purge/embargo: `1/1/1`
- Forecast cadence: per WPSR release only
- Model: logistic regression
- Hyperparameters: fixed before running
- Refits: monthly rolling-origin
- Minimum train events: pre-register explicitly
- Features:
  - `crude_stock_change_z`
  - `product_stock_change_z`
  - `refinery_utilization_change_z`
  - `net_import_change_z`
  - optional only if preregistered: `cushing_stock_change_z`
  - optional only if preregistered: strict previous-trading-day WTI lag

Important: if the candidate includes WTI lag, report both:

1. WPSR values only.
2. WPSR values plus WTI lag.

Those are different claims. Do not silently select the better one after seeing
results.

## Implementation Plan

1. Copy the structure of `feasibility/candidates/wpsr_inventory_3d/` into a new
   `wpsr_inventory_1d` package.
2. Copy `audit_wpsr_inventory_3d_phase3.py` into a new 1d audit script.
3. Change constants:
   - `HORIZON_DAYS = 1`
   - `PURGE_DAYS = 1`
   - `EMBARGO_DAYS = 1`
   - output/report filenames to 1d names
   - target name from `wti_3d_return_sign` to `wti_1d_return_sign`
4. Keep WPSR decision timestamps from `load_family_decision_events(...,
   WPSR_FAMILY)`.
5. Build WPSR feature rows by release timestamp, then anchor to the target price
   anchor timestamp exactly as the 3d script does.
6. Build labels with `build_target_observations([wpsr_events], prices,
   horizon_days=1)`.
7. Use `kept_decision_ts(..., purge_days=1, embargo_days=1)`.
8. Run rolling-origin walk-forward and write residuals indexed by `decision_ts`.
9. Invoke the residual-mode harness.
10. Write a report that includes zero baseline and majority baseline.

## A Key Design Choice To Decide Up Front

The old 3d script filters target observations to post-2020 before the
walk-forward audit, then applies a 52-week warmup. That costs roughly the first
year of post-2020 scored residuals.

For this 1d candidate, decide and document one of:

1. Strict post-2020-only training and testing, matching the existing audit
   pattern.
2. Pre-2020 training/warmup allowed, with post-2020 results still reported as
   the evaluation window.

Do not make this choice after looking at results. If choosing option 2, explain
why it is governance-safe and how it avoids contaminating the forward-holdout
logic.

## Required Metrics

The report must show:

| Metric | Required |
| --- | --- |
| scored_events | yes |
| model_accuracy | yes |
| zero_return_baseline_accuracy | yes |
| majority_baseline_accuracy | yes |
| gain_vs_zero_return_baseline_pp | yes |
| gain_vs_majority_baseline_pp | yes |
| n_after_purge_embargo | yes |
| HAC effective N on residuals | yes |
| block-bootstrap effective N on residuals | yes |
| verdict | yes |

The old reports only gate formally on zero-baseline gain. This task must also
make majority-baseline performance front-and-center.

## Success Criteria

Minimum useful result:

- Positive gain versus zero-return baseline.
- Positive gain versus majority baseline.
- HAC effective N >= 250.
- Block-bootstrap effective N >= 250.
- No changes to the locked 1d forward candidate.
- No lock-integrity break.
- Tests pass.

Preferred result:

- Gain versus majority baseline >= +2.0 pp.
- Clear feature provenance.
- Stable sign/performance after simple robustness checks:
  - remove one feature group at a time
  - date-shift placebo fails
  - no single year dominates the result

If the candidate fails, preserve the negative result as a report. Do not tune it
against the failed output.

## Tests To Add

Add tests in `tests/feasibility/candidates/test_wpsr_inventory_1d.py`.

Required test coverage:

1. Feature builder uses prior releases only for rolling z-score statistics.
2. Missing required WPSR series raises a clear error.
3. Target feature alignment does not use event-day WTI close as a feature.
4. Walk-forward audit returns zero and majority baseline metrics.
5. Residual CSV has `decision_ts,residual` columns and UTC timestamps.
6. Audit script can run with a small fixture and `--skip-harness`.

Also run existing relevant tests:

```bash
.venv/bin/pytest \
  tests/feasibility/candidates/test_wpsr_inventory_3d.py \
  tests/feasibility/candidates/test_wti_lag_1d.py \
  tests/feasibility/test_wti_lag_1d_forward.py \
  tests/v2/ingest/test_eia_wpsr_archive.py \
  tests/v2/ingest/test_eia_wpsr_fetcher.py \
  -q
```

Full verification before final commit:

```bash
.venv/bin/pytest tests/ -q
.venv/bin/ruff check .
```

`ruff format --check .` currently has repo-wide formatting debt in unrelated
files. For this task, at minimum run `ruff format --check` on touched files.

## Commands For A Clean Audit Run

After implementation:

```bash
cd /Users/henrirapson/projects/multi-desk-trading

.venv/bin/python feasibility/scripts/audit_wpsr_inventory_1d_phase3.py

cat feasibility/reports/terminal_2026-05-01_phase3_audit_wpsr_inventory_1d.md

.venv/bin/python - <<'PY'
from feasibility.scripts.forward_wti_lag_1d import verify_forecast_chain, verify_lock_integrity
print(verify_lock_integrity())
print(verify_forecast_chain())
PY
```

The forward lock must remain ok.

## Common Pitfalls

- Calling the feature an "expectations surprise" if it is only a trailing
  release-change z-score. Analyst-consensus expectations are not present.
- Using EIA current revised series history for historical first-release tests.
- Accidentally using event-day WTI close before it is available.
- Changing `feasibility/tractability_v1.py` and breaking the forward lock.
- Reporting only gain versus zero baseline and hiding majority-baseline failure.
- Using all calendar families while only WPSR events have WPSR value features.
- Treating sign-unit candidates as production desks. These are audit-only unless
  a promotion review defines a controller-compatible decision unit.

## Definition Of Done

A good handoff-complete commit contains:

- New prereg for WPSR 1d.
- New audit-only candidate package.
- New audit script.
- Residual CSV.
- Phase 3 residual-mode manifest.
- Human report with majority-baseline result.
- Focused tests.
- Verification output summarized in the final message.
- No changes to the locked 1d forward candidate files.

If the result fails, the final answer should say so plainly and include the
failure mode: accuracy, majority baseline, HAC N, bootstrap N, or data
availability.
