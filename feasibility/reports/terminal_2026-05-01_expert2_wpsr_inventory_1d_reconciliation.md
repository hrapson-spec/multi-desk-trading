# Expert 2 WPSR Inventory 1d Reconciliation

**Date**: 2026-05-01
**Branch**: feasibility-harness-v0
**Base commit inspected**: 4c47cf0 `feat(feasibility): audit WPSR inventory 1d candidate`

## Context

Expert 2 reported an additive patch for a WPSR inventory 1d audit with two
pre-committed model arms:

- `wpsr_only_core4`: the four WPSR features reused from the 3d candidate
  (`crude_stock_change_z`, `product_stock_change_z`,
  `refinery_utilization_change_z`, `net_import_change_z`)
- `wpsr_plus_lag_core4`: the same four WPSR features plus the strict previous
  trading day WTI 1d lag feature

Their patch was not present in this checkout, and no remote branch contained it.
The existing local branch instead contains the earlier seven-feature WPSR-only
audit committed at `4c47cf0`.

To answer the empirical question without overwriting the existing clean negative
result, I ran the Expert 2 model arms directly against the local PIT/WTI data
using the committed WPSR 1d audit helpers and temporary residual/manifest paths
under `/tmp`.

## Local Data Run

Command shape:

```bash
.venv/bin/python - <<'PY'
# Imports existing WPSR 1d audit helpers, selects the four core WPSR features,
# appends strict_previous_trading_day_log_return for the secondary arm, runs
# monthly expanding-window walk-forward, writes temporary residual CSVs, and
# invokes tractability_v1 residual-mode harness for each arm.
PY
```

Inputs:

- PIT root: `data/pit_store`
- Target: `wti_1d_return_sign`
- Family: `wpsr`
- Horizon/purge/embargo: `1/1/1`
- Evaluation: post-2020 target anchors
- Training: pre-2020 rows allowed for warmup, with label availability gated
  before each monthly refit

## Results

| Model arm | rows | scored_events | accuracy | zero baseline | majority baseline | gain vs zero | gain vs majority | HAC N | bootstrap N | n_star | Expert 2 gates |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `wpsr_only_core4` | 715 | 327 | 49.54% | 48.01% | 51.99% | +1.53 pp | -2.45 pp | 295 | 305 | 295 | FAIL |
| `wpsr_plus_lag_core4` | 715 | 327 | 52.29% | 48.01% | 51.99% | +4.28 pp | +0.31 pp | 314 | 327 | 314 | FAIL |

Expert 2's stated hard gates were:

- gain vs zero baseline >= +5.00 pp
- gain vs majority baseline >= +2.00 pp
- HAC effective N >= 250
- block-bootstrap effective N >= 250

Both arms clear the effective-N gates. Neither arm clears the skill gates.

## Interpretation

The second expert's more conservative four-feature WPSR-only primary is also a
negative result. It improves on the seven-feature WPSR-only audit but still loses
to the majority-sign baseline by 2.45 pp.

The WPSR+lag secondary is better, but still not admissible. It misses the
zero-baseline gate by 0.72 pp and misses the majority gate by 1.69 pp. The small
+0.31 pp majority gain is also not enough to distinguish it from the already
locked WTI-lag branch in any promotion-relevant way.

## Decision

Classification: `VALID_NEGATIVE_RESULT`

Recommended action:

- Do not promote either WPSR inventory 1d arm.
- Preserve the negative evidence.
- Treat future WPSR-for-WTI-sign work as low priority unless it introduces a
  genuinely new prior-motivated observable, such as consensus inventory surprise
  vintages or intraday price reaction features, with a fresh pre-registration.

