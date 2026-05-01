# prompt_balance_nowcast — mechanism memo (Layer 2)

**Status**: S0 concept; scaffold implementation shipped in `desk.py`.
**Family**: `oil_wti_5d`
**Target variable**: `WTI_FRONT_1W_LOG_RETURN` (5 trading-day horizon)
**Decision unit**: `log_return`

---

## 1. Claim

Short-horizon WTI front-month log-return contains a component
explainable by the state of the prompt U.S. physical crude balance as
reported in the EIA Weekly Petroleum Status Report (WPSR). When
reported stocks rise relative to seasonal and secular norms (crude +
products), and when refinery throughput weakens, front-month sellers
face greater disposal pressure and the curve bears a bearish tilt that
propagates into the subsequent week's flat price. The converse holds
for stock draws + strong runs.

This is **not** a claim about mechanistic prediction of the oil market.
It is a claim that a single, well-specified reported-balance signal
carries 5-day predictive content above a naive empirical baseline, in
the specific regime where (a) OPEC+ policy is unchanged, (b) no
acute geopolitical disruption is active, and (c) macro-asset channels
are not the dominant marginal pricing force.

## 2. Mechanism sketch

Let `I_t` = prompt inventory deviation (crude + products, deseasonalised
and standardised, expressed in days of consumption).
Let `R_t` = refinery throughput deviation (deseasonalised).
Let `N_t` = net imports (imports − exports), deseasonalised.
Let `S_t` = front-month / next-month calendar spread.

The claim:

    E[Y_{t,t+5} | I_t, R_t, N_t, S_t] = f(I_t, R_t, N_t, S_t)

where `Y_{t,t+5}` is the 5-trading-day log return of the front-month
WTI contract under `rolling_rule_v1` and `f` is a shrinkage-friendly
monotone function with signed predictions:

- `I_t` large and positive (build) → negative expected return
- `R_t` large and positive (runs up) → positive expected return
- `N_t` large and positive (net imports rising) → negative expected return
- `S_t` steeply in contango (M1 − M2 large negative) → negative expected return

The magnitudes are free parameters to be fitted; the signs are
pre-registered and will be enforced as a hard-gate invariant in the
Layer-3 walk-forward evaluation.

## 3. Observability (Layer 2 proof-of-observability)

Every input listed above is derivable from the PIT-safe feature view
under docs/v2/v2_data_contract.md §4 with the following source lineage:

| Input | Source | Release | Lag |
|---|---|---|---|
| crude_stocks, gasoline_stocks, distillate_stocks | `eia/wpsr` | Wed ≥10:30 ET + latency guard | 5 days (week-ending Friday prior) |
| refinery_runs | `eia/wpsr` | Wed ≥10:30 ET + latency guard | 5 days |
| crude_imports, crude_exports | `eia/wpsr` | Wed ≥10:30 ET + latency guard | 5 days |
| wti_calendar_spread_1_2 | `wti_front_month` | daily ≥14:30 ET settlement | 0 days |

All source rows are recorded with full vintage provenance; the
release-calendar YAMLs at `v2/pit_store/calendars/` enforce timing in
tests and in the Layer-1 PIT audit.

## 4. Simpler-benchmark exclusion (Layer 2)

The promotion evidence must demonstrate that the mechanism above adds
signal over **both** of:

- **B0** zero-mean Gaussian with EWMA-vol dispersion (no conditioning);
- **B1** empirical 5-day return distribution over the training window
  (unconditional historical).

A single-scalar residual model over `I_t` alone is a useful ablation
against this full four-feature claim; it is ordered to run as a
Layer-3 robustness pass.

## 5. Known limitations (registered as capability debits at S0)

- Seasonality adjustment is model-internal and will be pinned in the
  prereg; no publisher-provided deseasonalised series is used.
- Calendar-spread (`wti_calendar_spread_1_2`) is marked `required=False`
  at scaffold-time; it will become `required=True` in the S1→S2 prereg
  once the Layer-1 audit confirms the spread series is defensibly
  reconstructible over the declared training window.
- No desk-side event gating: around OPEC+ meetings, hurricanes, and
  refinery fires the mechanism is known to be swamped by event-driven
  flow. That is `oil_disruption_event`'s job (v2.1). Until v2.1 lands,
  calendar-aware abstention rules in this desk's prereg will suppress
  forecasts on explicitly listed event windows.

## 6. Scaffold vs production

`desk.py` currently emits a **B0-equivalent** Gaussian quantile vector.
It is valid under the v2 contract and passes every structural check,
but it is **not** a promotable model. Promotion from S0 requires:

1. Layer-1 audit (decides training window).
2. Dynamic-factor or state-space nowcast implementation replacing the
   scaffold forecast logic.
3. Pre-registered hyperparameters (Regime A, fully frozen).
4. Layer-3 ROWF-CPCV run beating B0 + B1 on pinball + approx-CRPS.
5. Challenger-agent adversarial memo + rebuttal matrix.

Until these ship, this desk stays at S0 and its scaffold output MUST
NOT be used for any economic claim.

## 7. Document hash

After S0→S1 promotion this file is locked; its SHA-256 goes into the
prereg at `docs/v2/hashes/` alongside the contract receipts.
