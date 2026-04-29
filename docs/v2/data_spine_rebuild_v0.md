# Data Spine Rebuild v0

Date: 2026-04-29
Scope: crude feasibility harness, PIT WPSR/WTI spine

## Verdict

The existing v2 PIT primitives are usable, but the data spine itself must
be rebuilt before any candidate audit or modelling work. The current EIA
API ingester fetches current historical snapshots and writes one manifest
vintage per series. That is not a historical first-release WPSR archive
and is not admissible for WPSR feature training.

The primary rebuild path is now EIA's official WPSR archive, not the EIA
series API. EIA's archive exposes issue pages by release date, and recent
issue pages expose table CSV links. The WPSR schedule states that summary,
overview, and Tables 1-14 CSV/XLS files are released after 10:30 a.m. ET,
with holiday exceptions.

References:

- EIA WPSR archive: https://www.eia.gov/petroleum/supply/weekly/archive/
- Example archived issue: https://www.eia.gov/petroleum/supply/weekly/archive/2022/2022_04_06/wpsr_2022_04_06.php
- EIA WPSR release schedule: https://www.eia.gov/petroleum/supply/weekly/schedule.php

## Source Contract

WPSR is no longer represented as an atomic source.

```text
source=eia
dataset=wpsr
series=<table-derived or EIA series id>
view=eia_wpsr
feature=eia__wpsr__<series>__<field>
```

This leaves room for future EIA datasets such as STEO or monthly
petroleum without overloading the source name.

## Vintage Quality

Allowed values:

- `true_first_release`: first-release archive value with release timing.
- `release_lag_safe_revision_unknown`: data value exists and release lag is
  safe, but the value may be revised.
- `latest_snapshot_not_pit`: current historical snapshot with no usable
  release-vintage information.
- `calendar_only_rejected`: calendar timestamp exists but no data payload.

Admissibility rules:

- `true_first_release` is admissible.
- `release_lag_safe_revision_unknown` is admissible only for tractability
  counting, return-sign target checks, and broad coverage diagnostics.
- `release_lag_safe_revision_unknown` is forbidden for inventory-surprise
  magnitude and stock-change features.
- `latest_snapshot_not_pit` and `calendar_only_rejected` are always rejected
  by the feature layer.

Propagation rule:

```text
If any admitted input vintage has vintage_quality != true_first_release,
then every derived feature, FeatureView, ForecastV2 metadata block, run
manifest, and report must retain the worst upstream vintage_quality and
name the affected source/dataset/series.
```

## Timing Rules

The WPSR release calendar uses `America/New_York`, not a fixed UTC offset.
The calendar also carries `latency_guard_minutes: 5`, so the PIT reader
must not expose an issue until `usable_after_ts = release_ts + 5 minutes`.

Official issue dates from EIA archive pages are authoritative when they
diverge from a derived Wednesday schedule.

## Non-Goals

- Do not treat FRED `DCOILWTICO` spot as an executable CL/MCL futures
  return target.
- Do not use the spot proxy for `CL_front_month_backtest`,
  `MCL_execution_replay`, or executable futures replay.
- Do not train inventory-surprise models on revision-unknown WPSR values.
- Do not overwrite the original
  `feasibility/reports/terminal_tractability_v0.md` report; post-rebuild
  tractability gets a new dated report.

## Acceptance Tests

The rebuild must keep these tests green:

- `test_wpsr_pre_release_sees_prior_week_post_release_sees_current`
- `test_as_of_respects_usable_after_latency_guard`
- `test_release_timezone_dst_uses_america_new_york`
- `test_revision_quality_blocks_surprise`
- `test_revision_quality_propagation`
- `test_latest_snapshot_not_pit_rejected_even_for_generic_feature`
- `test_public_data_runbook_cli_commands_parse`

## Next Implementation Slice

1. Use `v2.ingest.eia_wpsr_archive.EIAWPSRArchiveIngester` to populate
   post-2020 WPSR first-release vintages from official archive CSV tables.
2. Run a sampled coverage check across 2020-2026 issue pages and table CSV
   links before a full backfill.
3. Rerun tractability using the registered `DCOILWTICO` tractability-only
   spot proxy and write
   `feasibility/reports/terminal_YYYY-MM-DD_tractability_post_rebuild.md`.
