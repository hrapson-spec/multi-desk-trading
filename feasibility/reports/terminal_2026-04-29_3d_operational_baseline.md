# Crude Feasibility Harness — 3d Horizon Promoted to Operational Default

Created: 2026-04-29
Branch: `feasibility-harness-v0`
Schema: `tractability.v1.0`

## Decision

The harness's default horizon is now **3 days**. Prior default was 5
days (locked v0). Spec v1 §13 already admitted `WTI_FRONT_3D_LOG_RETURN`
and `WTI_FRONT_3D_RETURN_SIGN` as targets backed by the dependence
analysis at `docs/v2/dependence_analysis_3d_horizon.md`. This report
documents the **operational promotion** from variant to default.

The locked v0 5d result remains byte-identically reproducible via
explicit flags. The v0 invariant tests still pass.

## Verification (live, this commit)

| Invocation | min_effective_n | Rule |
|---|---:|---|
| `--families wpsr,fomc,opec_ministerial,psm,gpr` (no horizon flags → defaults to 3d) | **310** | `continue` |
| `--families wpsr --horizon-days 5 --purge-days 5 --embargo-days 5` (explicit v0 5d) | **163** | `continue_small_model_only` |
| `--families wpsr,fomc,steo,opec_ministerial,psm,gpr --horizon-days 1 --purge-days 1 --embargo-days 1` (1d, unaffected) | **648** | `continue` |

3d default clears Phase 3 floor (≥250) by 60 events. v0 5d invariant
preserved. 1d horizon (the live admissible-provisional candidate's
workflow at `feasibility/forward/wti_lag_1d/`) unaffected by the
default change since it has always passed explicit horizon flags.

## What changed

### `feasibility/tractability_v1.py` — six default-value sites

| Line (post-edit) | Symbol | Old | New |
|---|---|---:|---:|
| 290 | `compute_hac_effective_n.horizon_days` default | 5 | 3 |
| 291 | `compute_hac_effective_n.embargo_days` default | 5 | 3 |
| 1178 | `_default_targets.horizon_days` default | 5 | 3 |
| 1230 | `--purge-days` argparse default | 5 | 3 |
| 1231 | `--embargo-days` argparse default | 5 | 3 |
| 1235 | `--horizon-days` argparse default | 5 | 3 |

`--horizon-days` help text updated: explicitly states 3d is the
spec v1 §13 operational baseline and documents the explicit-flag
recipe for v0 5d reproducibility.

### `tests/feasibility/test_tractability_v1.py` — three v0-invariant pins

| Line | Test | Pin |
|---|---|---|
| 302 | `test_v1_with_wpsr_only_matches_v0_post2020_n` | `_default_targets(horizon_days=5)` |
| 549 | `test_compute_additive_n_contribution_steo_zero_delta_after_anchor_dedup` | `_default_targets(horizon_days=5)` |
| 1064 | `test_v0_invariant_preserved_with_csv_path` | `_default_targets(horizon_days=5)` |

Each test asserts `wti_5d_*` target names AND specific 5d-era N
values; the explicit pin keeps them exercising the v0 invariant
under the new default.

### `feasibility/reports/n_requirement_spec_v1.md` — §13 wording

§13 retitled "3d operational default (promoted from variant
2026-04-29)". §13.1 numbers updated to the post-bug-fix corrected
values (310/285 instead of the inflated 365/401). The pre-bug-fix
inflated numbers are explicitly marked as superseded.

## Test status

- **947 passed, 1 skipped** (no regression from baseline before the flip)
- Ruff: clean
- v0 byte-identical reproducibility: verified
- 1d candidate workflow: untouched (explicit flags throughout)

## Operator notes

1. **Downstream callers** of `feasibility.tractability_v1` or
   importers of `_default_targets()` without explicit horizon args
   will silently shift from 5d to 3d output. Audit needed:
   ```
   grep -r "tractability_v1\|_default_targets" --include="*.py" .
   ```
   At time of writing, all such callsites within
   `feasibility/scripts/` and `tests/feasibility/` either pass
   explicit horizons (1d audit, candidate audits, forward-lock
   scripts) or are the v0-invariant tests just pinned. No external
   downstream consumers detected.

2. **Magnitude target at 3d**: Spec v1 §13.2 forbids magnitude for
   Phase 3 promotion (HAC=133 < 250 floor at 3d). The harness's
   `_default_targets` still emits the magnitude target for
   diagnostic reporting; consumer policy enforces the §13.2 ban.

3. **B9 guard semantics**: the existing
   `test_compute_additive_n_contribution_steo_zero_delta_after_anchor_dedup`
   measures STEO non-additive-ness at 5d (delta=0 after anchor
   dedup). At 3d default, STEO's contribution against various base
   sets has not been re-measured. Tracked as **D-feas-5**: B9 guard
   re-measurement at 3d is operator runbook follow-up; default
   harness behavior is unaffected (the guard only fires when
   `--reject-non-additive` is passed).

4. **Live 1d candidate**: forward-locked at
   `feasibility/forward/wti_lag_1d/lock.json` with 42 events queued
   over the next 120 days. This default flip does not interact with
   the lock contract (which uses explicit 1d horizon throughout).

## Reproducibility

```
cd /Users/henrirapson/projects/multi-desk-trading

# 3d default
.venv/bin/python -m feasibility.tractability_v1 \
    --families wpsr,fomc,opec_ministerial,psm,gpr
# Expected: rule "continue", min_effective_n=310

# v0 5d invariant
.venv/bin/python -m feasibility.tractability_v1 \
    --families wpsr \
    --horizon-days 5 --purge-days 5 --embargo-days 5
# Expected: rule "continue_small_model_only", min_effective_n=163

# Full suite
.venv/bin/pytest tests/ -q
# Expected: 947 passed, 1 skipped
```

## Files

**Modified**:
- `feasibility/tractability_v1.py` (6 default sites + help text)
- `tests/feasibility/test_tractability_v1.py` (3 explicit `horizon_days=5` pins)
- `feasibility/reports/n_requirement_spec_v1.md` (§13 wording promotion)

**New**:
- `feasibility/outputs/tractability_v1_3d_default_baseline.json` (new default-baseline manifest)
- `feasibility/reports/terminal_2026-04-29_3d_operational_baseline.md` (this report)

**NOT modified** (frozen surfaces respected):
- `contracts/target_variables.py` (3d targets pre-existing per 53f4fac)
- `feasibility/reports/n_requirement_spec_v0.md` (locked record)
- All v2/* (frozen-surface boundary)
