# Hedging-demand desk — spec

**Phase 2 scale-out desk 2 (spec v1.13).** Equity-VRP analogue to the oil `supply` desk. Forecasts next-period 30-day forward implied vol (target `VIX_30D_FORWARD`) from institutional put-buying pressure.

## Purpose

Capture the structural signal that portfolio-hedging flow raises implied vol (especially OTM skew) without necessarily changing realised vol. This is the flow-side mechanism underlying the equity volatility risk premium.

## Inputs

### Observation channels (Phase 2 MVP synthetic)

| Channel | Source | Semantics |
|---|---|---|
| `hedging_demand_level` | `sim_equity_vrp.observations.EquityObservationChannels.by_desk["hedging_demand"]` | Noisy OU-process observation of institutional put-buying pressure |
| `put_skew_proxy` | Same | Noisy observation of `hedging_demand × vol_level`. SIGNED — unlike real put skew which is strictly ≥ 0 |

### Feed → channel mapping

| `feed_names` entry | Observation channel | Production source (Phase 3) |
|---|---|---|
| `cboe_open_interest` | `hedging_demand_level` | CBOE options open interest (put/call OI snapshots) |
| `option_volume` | `put_skew_proxy` | Daily option volume (put/call totals) |

The scheduler's `data_ingestion_failure` handler routes events to this desk when either feed fails, via `config/data_sources.yaml` `consumed_by: [hedging_demand]`.

## Output

```
Forecast(
    target_variable = "vix_30d_forward",
    point_estimate  = <predicted vol>,
    directional_claim.sign = <derived from score: "positive" | "negative" | "none">,
    staleness       = <from feed_incidents registry>,
)
```

### Sign derivation

**Not hardcoded.** The ridge model emits signed predictions over log-return of vol. The desk derives `sign` from the score at each emission:

| Condition | Sign |
|---|---|
| `score > 1e-6` | `"positive"` |
| `score < -1e-6` | `"negative"` |
| `\|score\| ≤ 1e-6` | `"none"` |

Rationale: hardcoding `sign="positive"` while the score occasionally goes negative produces internally-incoherent Forecast objects that downstream grading reads inconsistently. This is one of the design-review (M-3) corrections from the `phase2-desk2-hedging-demand-v1.13` ship.

## Model

`ClassicalHedgingDemandModel` — ridge over 5 features:

| Feature | Description |
|---|---|
| `hd_last` | Most recent hedging_demand observation |
| `hd_mean` | Mean of hedging_demand over lookback window |
| `hd_trend` | Linear-fit slope of hedging_demand over lookback |
| `skew_last` | Most recent put_skew_proxy observation |
| `skew_mean` | Mean of put_skew_proxy over lookback |

Fit target: log-return of `vol_level` (= `market_price`) over `horizon_days = 3`. Prediction: next-period vol level.

### Hyperparameter notes

- `lookback=15` (days). Chosen so the summary window > 2× the hd process half-life (≈ 6.6 days at `hd_ar1=0.9`). Governs the *summary window*, not lag depth — the ridge uses 5 summary statistics, not 15 lagged values. Changing this is a capability debit.
- `alpha=1e-3`. Mirror of oil supply/demand desks' small-alpha ridge for return-space targets.
- `horizon_days=3`. Matches `ClassicalDealerInventoryModel`.

### Train/serve distribution (M-1 fix)

**Fit on the same noisy observation channels the desk reads at serve time**, NOT on clean latent (`path.hedging_demand` / `path.put_skew_proxy`). Train/serve distribution matching — production will never see clean latent.

## Gates

- **Gate 3 — DeskProtocol conformance + attribute parity** (strict). Must pass. Portability invariant per §8.4. (Note: the existing gate harness uses `run_controller_fn=lambda: True`, making the runtime hot-swap claim weaker than the spec language implies; see capability-debit D9 for the baseline fix commitment.)
- **Gate 1 — skill** (capability claim). Ridge should beat the vol-random-walk baseline on log-return of vol. May fail on the minimal MVP market; that failure expands capability-debit D7.
- **Gate 2 — sign preservation** (capability claim). Positive-sign convention dev → test. Dynamic-sign derivation means correlations on dev vs test should align in magnitude.

### Pinned G1/G2 metrics

`tests/test_hedging_demand_gates.py::test_hedging_demand_classical_three_gates_on_mvp_market` pins the exact `relative_improvement` / `dev_corr` / `test_corr` values recorded at first test run. Drift triggers a test failure — the plan's soft "print only" approach would have hidden gradual regression.

## put_skew_proxy semantics caveat

The `put_skew_proxy` = `hedging_demand × vol_level` is signed by construction. Real put skew is strictly ≥ 0 (OTM put IV ≥ ATM IV in equity indices). Any downstream consumer that assumes `put_skew_proxy ≥ 0` will silently mishandle the synthetic signal. Audit before wiring into production. Fix options: tanh squashing, absolute value, or exponentiation to a positive surface.

## Phase 2 scale-out position

Desk 2 of 5. Remaining desks (hot-swappable against the same interface):
- `term_structure` (↔ oil demand) — implied-realised spread
- `earnings_calendar` (↔ oil geopolitics) — event-driven vol expansion
- `macro_regime` (↔ oil macro) — equity vol-regime classifier
