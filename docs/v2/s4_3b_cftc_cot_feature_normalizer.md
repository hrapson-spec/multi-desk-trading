# S4-3B CFTC COT feature normalizer

- **Status**: implemented and verified
- **Created**: 2026-04-24
- **Predecessor**: `s4_3a_exogenous_feature_hook.md`
- **Stage**: S4-3B exogenous WTI feature adapter

## Objective

S4-3B implements the first concrete exogenous feature adapter for the S4-3
model-quality gate: CFTC Commitments of Traders positioning features for WTI.

The adapter does not fetch from the network yet. It normalizes an official CFTC
disaggregated futures-only CSV/text shape into a release-timestamped feature
frame that can be passed into the S4-3 exogenous hook.

References:

- CFTC Historical Compressed files:
  `https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm`
- CFTC variable names for disaggregated COT reports:
  `https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalViewable/CFTC_023168`

## Implementation

Updated:

- `v2/ingest/cftc_cot.py`
- `tests/v2/ingest/test_cftc_cot.py`

Function:

```python
normalize_wti_disaggregated_cot(data, market_code="067651")
```

WTI market code:

```text
067651
```

## PIT Semantics

CFTC COT positions are reported as of Tuesday, but are not decision-eligible
until publication. The normalizer therefore indexes rows by:

```text
Friday 15:30 America/New_York, converted to UTC
```

Example:

| Report date | Release timestamp |
|---|---|
| 2026-04-21 | 2026-04-24T19:30:00Z |

This index is designed for backward as-of merging into the S4-3 model-quality
gate.

## Features

The normalizer produces:

- `open_interest`
- `prod_merc_net`
- `swap_net`
- `managed_money_net`
- `other_reportable_net`
- `nonreportable_net`
- Net positioning divided by open interest for each category.

## Verification

- `uv run pytest tests/v2/ingest/test_cftc_cot.py -q` -> 4 passed
- `uv run pytest tests/v2/ingest tests/v2/s4_0 -q` -> 51 passed
- `uv run ruff check v2/ingest v2/s4_0 tests/v2/ingest tests/v2/s4_0` -> all checks passed
- `uv run pytest tests/v2 -q` -> 282 passed

## Next Engineering Implication

The CFTC parser is ready to feed S4-3 once local CFTC historical files are
available. The next step is either:

- implement the network/download layer for official CFTC historical compressed
  files, or
- place downloaded CFTC files under the local evidence path and run S4-3 with
  the resulting positioning features.
