# Feasibility Harness v1 — WPSR + FOMC

Created: 2026-04-29
Schema: `tractability.v1.0`

## Verdict (Phase 0)

- Rule: `continue_small_model_only`
- Action: `remove_foundation_models_from_harness`
- min_effective_n (Phase 0): **207** (was 163 WPSR-only)
- Distance to Phase 3 entry (≥250): **43 events**

## What changed vs WPSR-only baseline

| Quantity | WPSR-only | WPSR + FOMC | Δ |
|---|---:|---:|---:|
| n_decision_timestamps | 327 | 429 | +102 |
| n_manifest_rows | 3924 | 4026 | +102 |
| n_post2020_raw (per target) | 326 | 428 | +102 |
| n_after_purge_embargo (per target) | 163 | **207** | **+44** |
| HAC NW for return_sign | 147 | 154 | +7 |
| HAC NW for return_magnitude | 66 | 82 | +16 |
| HAC NW for mae_conditional | 160 | 180 | +20 |

Adding 102 raw FOMC events (51 statements + 51 minutes) yields +44 effective
events post-thinning — a 27% increase in usable sample. The yield is
consistent with the §C plan estimate of "+30 to +40 effective add".

The HAC-adjusted estimates also rose because the additional events fall on
different days of the week (Wed/Mar/etc.) than the weekly WPSR Wed
cadence, breaking some volatility-clustering autocorrelation.

The Phase-3 strict-HAC reading still flags `return_magnitude` (effective
N = 82 under volatility clustering) as a watch item.

## FOMC ingester details

- Module: `v2/ingest/fomc_calendar.py` (calendar-encoded; statement +
  minutes events 2020-01-29 → 2026-04-08).
- Calendar: `v2/pit_store/calendars/fomc.yaml` (latency_guard=5min,
  release_cadence=irregular_scheduled, revision_policy=none).
- 102 manifest rows written with vintage_quality `true_first_release`.
- CLI: `python -m v2.ingest.cli backfill --source fomc_calendar`.
- Tests: `tests/v2/ingest/test_fomc_calendar.py` (12 tests pass).

## Observed positive rate

`return_sign` baseline shifted from 0.5613 (WPSR-only) to 0.6087
(WPSR + FOMC). Implication: the FOMC announcement window biases positively
in WTI (oil rallies on Fed liquidity expectations). For Phase 3 candidate
audit this means the per-event-family directional baseline must be
computed separately, not pooled. Spec §11 forbidden #4 already prohibits
N borrowing across targets; the same caution applies to per-family
positive-rate baselines within a target.

## Files

- `feasibility/outputs/tractability_v1_wpsr_plus_fomc.json` — full v1
  manifest with both families.
- `v2/ingest/fomc_calendar.py` — ingester.
- `v2/pit_store/calendars/fomc.yaml` — calendar metadata.
- `tests/v2/ingest/test_fomc_calendar.py` — unit tests.
- Tractability registry update at `feasibility/tractability_v1.py`
  (added `FOMC_FAMILY` to `DEFAULT_FAMILY_REGISTRY`).
- CLI registration at `v2/ingest/cli.py` (`fomc_calendar` source).

## Reproducibility

```
cd multi-desk-trading
.venv/bin/python -m v2.ingest.cli backfill --source fomc_calendar \
    --since 2020-01-01 --until 2026-04-29
.venv/bin/python -m feasibility.tractability_v1 --families wpsr,fomc \
    --output feasibility/outputs/tractability_v1_wpsr_plus_fomc.json
.venv/bin/pytest tests/v2/ingest/test_fomc_calendar.py tests/feasibility/ -v
```
