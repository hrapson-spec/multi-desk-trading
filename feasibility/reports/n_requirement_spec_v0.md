# Crude Feasibility Harness N Requirement Specification v0

Date: 2026-04-29
Scope: WTI/WPSR crude feasibility harness
Status: locked technical definition for interpreting tractability N

## 1. Executive Definition

The required N is not row count, bar count, PIT manifest count, or number of
model runs. The required N is:

```text
N_star = min_target(
    N_eff_oos_post2020_pit_clean_target_realizable_purged_embargoed_costed
)
```

In plain terms: the harness needs independent-ish, out-of-sample,
post-2020 decision events for which every feature was available point-in-time,
the target can be computed without lookahead, labels do not overlap after
purge/embargo, and, when execution is being evaluated, the trade would have
had a costed executable path.

For this project, the useful operating range is:

```text
hard_floor_for_any_research_continuation:      100 effective events
minimum_for_candidate_audit:                   250 effective events
useful_small_model_research_target:            500 effective events
complex_model_or_foundation_revisit_floor:    1000 effective events
```

The current post-rebuild tractability result is `N_star = 163`, which permits
small-model-only continuation for blunt candidate rejection, but not model
search, paper promotion, or foundation-model branches.

## 2. Non-Admissible N

The following counts must never be used as the statistical N for alpha claims:

- `pit_manifest_rows`: multiple source/series rows per WPSR release.
- `parquet_file_count`: storage completeness, not observations.
- `calendar_release_count`: release schedule count before target availability.
- `daily_price_bar_count`: repeated market bars, not WPSR decision events.
- `feature_cell_count`: rows times columns; this inflates evidence by feature
  dimensionality.
- `model_run_count`: search attempts; this consumes significance budget.
- `pretrained_model_token_count`: irrelevant to statistical validation of this
  strategy.
- `in_sample_training_rows`: admissible only for fitting; not for validation.

For the current rebuilt PIT store:

```text
WPSR manifest rows:        3948
distinct usable timestamps: 327
raw targetable events:      326
effective events:           163
```

Only the last line is the tractability N for current Phase 0.3 purposes.

## 3. Canonical Observation Unit

The canonical observation is one WPSR decision event:

```text
e_i = (
    decision_ts_i,
    PIT_snapshot_i,
    feature_vector_i,
    target_path_i,
    target_i
)
```

where:

```text
decision_ts_i = usable_after_ts of the relevant official WPSR issue
usable_after_ts = official_release_ts + latency_guard_minutes
official_release_ts = issue_date at 10:30 America/New_York
latency_guard_minutes = 5
```

`e_i` is admissible only if:

1. All required feature values come from PIT snapshots with
   `usable_after_ts <= decision_ts_i`.
2. Feature vintage quality is admissible for the feature use.
3. The target price series has an observable entry price at or after
   `decision_ts_i`.
4. The target path has enough forward observations for the declared horizon.
5. The observation is assigned to a validation fold without train/test leakage.

For Phase 0 tractability, `DCOILWTICO` is allowed only as a WTI spot proxy for
counting. For Phase 3 candidate audit and later, executable CL front futures
targets must replace the spot proxy.

## 4. N Pipeline

Every report must emit the full N waterfall:

```text
N_manifest_rows
N_series_rows_by_source
N_decision_timestamps
N_targetable_raw
N_post2020_raw
N_after_quality_filter
N_after_target_availability
N_after_purge_embargo
N_hac_or_block_adjusted
N_oos_total
N_oos_by_fold
N_by_regime
N_by_cost_bucket
N_star
```

Definitions:

```text
N_decision_timestamps =
    count_distinct(decision_ts)

N_targetable_raw =
    count(e_i where target_path_i exists for full horizon)

N_after_quality_filter =
    count(e_i where all feature vintage_quality values are admissible)

N_after_purge_embargo =
    max admissible subset of events such that retained labels do not overlap
    after purge and embargo constraints

N_oos_total =
    sum over validation folds of out-of-sample events after fold-specific
    purging and embargo

N_star =
    minimum target-level N used for the final decision rule
```

`N_star` must be computed per target. If return sign has 500 effective events
but MAE has 180, the harness-level N for a joint claim is 180.

## 5. Purge and Embargo Specification

For event `i`:

```text
d_i = decision_ts_i
h   = forecast_horizon_days
p   = purge_days
b   = embargo_days
L_i = [d_i, d_i + h]
E_i = [d_i - p, d_i + h + b]
```

Two events `i` and `j` cannot both contribute to independent validation when:

```text
L_i intersects L_j
or
d_j in E_i
or
d_i in E_j
```

The current Phase 0.3 tractability implementation uses a conservative thinning
rule:

```text
next_allowed = retained_decision_ts + purge_days + embargo_days
```

with:

```text
purge_days = 5
embargo_days = 5
horizon_days = 5
```

For walk-forward evaluation, the stricter fold rule applies:

```text
training events are removed if their label interval overlaps any test label
interval, and events immediately after the test block are embargoed.
```

## 6. Autocorrelation and Block Effective N

Purged/embargoed N is necessary but not sufficient. If the validation score
series remains autocorrelated, effective N must be reduced:

```text
N_eff_hac = N / (1 + 2 * sum_{k=1..K} rho_k)
```

where:

```text
rho_k = lag-k autocorrelation of the target score or residual series
K     = max lag with economically justified dependence, at least ceil(h / event_spacing)
```

The accepted N is:

```text
N_eff = floor(min(N_after_purge_embargo, N_eff_hac))
```

If autocorrelation estimates are unstable because N is small, use a block
bootstrap with block length at least:

```text
block_length >= ceil((horizon_days + embargo_days) / median_event_spacing_days)
```

and report the bootstrap-implied effective count.

## 7. Power Targets

Using the current post-rebuild WPSR/WTI tractability distribution:

```text
baseline directional majority rate: 56.13%
5d return magnitude sample std:     0.05486 log-return units
5d MAE sample std:                  0.02145 log-return units
alpha:                              0.05
power:                              0.80
```

Single pre-registered test power:

| Effective N | Detectable sign lift | Detectable 5d magnitude effect |
|---:|---:|---:|
| 163 | 10.72 pp | 0.0120 |
| 250 | 8.69 pp | 0.0097 |
| 500 | 6.17 pp | 0.0069 |
| 750 | 5.05 pp | 0.0056 |
| 1000 | 4.38 pp | 0.0049 |
| 1500 | 3.58 pp | 0.0040 |
| 2000 | 3.10 pp | 0.0034 |

Twelve-run search-budget adjusted power using Bonferroni
`alpha_i = 0.05 / 12`:

| Effective N | Detectable sign lift | Detectable 5d magnitude effect |
|---:|---:|---:|
| 163 | 14.15 pp | 0.0159 |
| 250 | 11.48 pp | 0.0129 |
| 500 | 8.16 pp | 0.0091 |
| 750 | 6.68 pp | 0.0074 |
| 1000 | 5.79 pp | 0.0064 |
| 1500 | 4.73 pp | 0.0053 |
| 2000 | 4.10 pp | 0.0045 |

Required N for directional lift detection:

| Desired detectable sign lift | Single test N | 12-run adjusted N |
|---:|---:|---:|
| 10 pp | 188 | 332 |
| 8 pp | 296 | 521 |
| 6 pp | 530 | 931 |
| 5 pp | 765 | 1343 |
| 4 pp | 1199 | 2102 |
| 3 pp | 2136 | 3744 |

This is why `N = 163` is not a validation-quality sample unless the edge is
very large.

## 8. Model Complexity Constraints

For binary directional models:

```text
minority_class_N = min(count(y=1), count(y=0))
effective_parameters <= floor(minority_class_N / 20)
```

At `N = 163` and observed majority rate near 56%, the minority class count is
about 72, so a directional logistic model should have no more than 3 effective
degrees of freedom. This excludes broad feature searches.

For quantile or tail models:

```text
N_eff * min(q, 1 - q) >= 30
```

Therefore a 10% or 90% quantile model requires:

```text
N_eff >= 300
```

For regime-conditioned models:

```text
min_regime_N_eff >= 150
```

If using three regimes, the practical total requirement is therefore at least
450 effective observations, and usually closer to 500-750 after imbalance.

For any tree/boosting model:

```text
N_eff >= 500
max_feature_sets <= 3
max_model_families <= 2
max_total_runs <= 12
```

Tree models at `N < 500` may be used only as exploratory diagnostics, not as
paper candidates.

## 9. Phase Gates

### Phase 0 Tractability

```text
N_star < 100      => stop
100 <= N < 250    => continue small-model-only; no Phase 4 model search
250 <= N < 500    => candidate audit allowed; highly constrained model search
500 <= N < 1000   => useful small-model research
N >= 1000         => foundation-model revisit becomes statistically discussable
```

### Phase 3 Candidate Audit

Minimum requirement to retain a research candidate:

```text
N_eff_oos_post2020 >= 250
and observed effect >= precomputed MDE
and candidate beats null plus simple baselines after costs
and DSR/PBO checks do not reject
```

If `100 <= N < 250`, Phase 3 may still reject candidates, but it must not
promote any candidate to paper authority unless the pre-registered edge size is
larger than the MDE at that N.

### Phase 4 Small-Model Research

Entry requirement:

```text
N_eff_oos_post2020 >= 250
feasible execution path exists
at least one Phase 3 candidate has non-reject verdict
```

Preferred requirement:

```text
N_eff_oos_post2020 >= 500
```

### Foundation Models

Entry requirement:

```text
N_eff_oos_post2020 >= 1000
and Phase 4 has a competitive paper candidate
and intraday budget is approved
and inference budget is approved
```

Foundation models cannot use pretraining scale as a substitute for
strategy-specific validation N.

## 10. Current Interpretation

Current post-rebuild result:

```text
N_manifest_rows:              3948
N_decision_timestamps:         327
N_targetable_raw:              326
N_after_purge_embargo:         163
N_star:                        163
```

Interpretation:

```text
allowed:
  - PIT spine validation
  - tractability reporting
  - blunt candidate rejection
  - simple comparator audits with very conservative conclusions

not allowed:
  - model search beyond tiny preregistered candidates
  - paper promotion
  - live promotion
  - foundation-model authority
  - claiming validation of subtle directional edges
```

At this N, a directional signal must improve over the baseline by roughly
10.7 percentage points in a single pre-registered test, or 14.2 percentage
points under a 12-run search adjustment, to be detectable at 5% significance
and 80% power.

## 11. How N May Be Increased Without Cheating

Permitted:

- Extend true first-release WPSR history earlier than 2020, but report
  pre-2020 and post-2020 separately.
- Use CL front futures daily history for candidate audit targets once the
  executable target spine is built.
- Add genuinely distinct event families only if each has its own PIT source
  contract and target definition.
- Reduce purge or embargo only with a written dependence analysis and a
  versioned gate change.
- Use daily targets only if repeated weekly WPSR feature exposure is corrected
  by HAC/block effective N and stale-feature policy.

Forbidden:

- Counting each WPSR series row as an observation.
- Counting every daily bar between WPSR releases as independent evidence
  without dependence adjustment.
- Pooling pre-2020 and post-2020 results into one promotion statistic without
  regime labeling.
- Borrowing N across targets with different missingness or execution filters.
- Treating spot-proxy tractability N as executable CL/MCL target N.

## 12. Mandatory Manifest Fields

Every tractability, candidate-audit, or model-search run manifest must include:

```yaml
n_manifest_rows:
n_decision_timestamps:
n_targetable_raw_by_target:
n_post2020_raw_by_target:
n_after_quality_filter_by_target:
n_after_purge_embargo_by_target:
n_hac_or_block_adjusted_by_target:
n_oos_by_fold:
n_by_regime:
n_by_cost_bucket:
n_star:
purge_days:
embargo_days:
horizon_days:
alpha_family:
alpha_per_test:
search_budget_runs:
minimum_detectable_effect_by_target:
price_target_kind:
price_target_forbidden_uses:
vintage_quality_distribution:
```

If any of these fields is absent, the run is not valid evidence.
