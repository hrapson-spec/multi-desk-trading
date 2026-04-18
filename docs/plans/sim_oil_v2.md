# `sim_oil_v2/` — Phase 3 oil-market simulator overhaul

**Status**: Design proposal (not yet scheduled for build).  
**Target phase**: Phase 3 (post-2026-07-17).  
**Author intent**: map the 7 oil stylised facts (Henri 2026-04-18) to concrete simulator variables + desk channels, preserving the §8.4 portability claim.

---

## 1. Purpose

The Phase 1 `sim/` package abstracts oil through a generic 5-factor stochastic process (Schwartz-Smith + OU + Hawkes). As documented in debit D10 (pending), none of the canonical oil stylised facts (inventories ↔ curve, WTI-Brent, spare capacity, global activity, refining margin, futures-first price discovery, producer stress ↔ hedging) is encoded as a structural invariant. The ridge-on-generic-OU desk models (D1) are a direct consequence: there is no oil-specific signal for them to recover.

**Phase 3 needs a simulator that imitates the canonical oil backbone.** The existing `sim/` stays untouched (test fixture for the architectural abstraction claim + Phase 1 completion manifest); `sim_oil_v2/` lands as a sibling, same pattern as `sim_equity_vrp/` did for Phase 2. Shared infra stays domain-neutral.

---

## 2. Design goals

1. **Encode the 7 stylised facts as sign-rules** in the latent-to-observable map. Not as regression targets — the sim is the ground truth, so the sign rules are how we *generate* data that respects the literature.
2. **Preserve portability.** Zero edits to `bus/`, `controller/`, `persistence/`, `research_loop/`, `attribution/`, `grading/`, `provenance/`, `eval/`, `soak/`, `scheduler/`, `contracts/v1.py`, `desks/base.py`, `desks/common/`. Enforced by the existing parametrised portability tests.
3. **Multi-tenor observable.** Emit a WTI term-structure (1st, 2nd, 6th, 12th month), a Brent front, a gasoline front, and inventory/macro series — not a single undifferentiated price.
4. **Regime + threshold non-linearity.** Keep the HMM regime layer for macro conditioning. Add piecewise / sigmoid mappings where the literature demands them (convenience yield vs inventory, price premium vs spare capacity).
5. **Calibration references.** Each variable's default parameters cite a literature source so the simulator is defensible, not hand-picked.

**Non-goals:**
- Full structural DSGE-style economy. The sim is a coherent synthetic fixture, not a production-grade oil-market model.
- Endogenous OPEC policy, trader behaviour, or macroeconomic feedback. Exogenous regime transitions are sufficient.
- Real-time news/text feeds. Hawkes events stand in for episodic surprise.
- USD as a core variable (per Henri: conditioning only, not backbone).
- Investor flows as foundational (per Henri: overlay, not skeleton).

---

## 3. Architecture — sibling package

```
sim_oil_v2/
├── __init__.py
├── latent_state.py        # 14-factor SDE + inventory/curve/refining/stress state
├── regimes.py             # 4-state HMM (equilibrium, supply_shock, demand_shock, stress)
├── curves.py              # term-structure construction from convenience-yield rule
├── inventories.py         # Cushing / US total / OECD stock dynamics + thresholds
├── refining.py            # gasoline-crude spread dynamics + seasonal overlay
├── spare_capacity.py      # OPEC spare capacity non-linear price premium
├── credit_stress.py       # producer credit + speculator capacity (Acharya mechanism)
├── observations.py        # per-desk channels (6 desks × N signals each)
└── README.md              # cites literature + points to this plan
```

Portability test extends to scan `sim_oil_v2/` for oil-domain vocab in shared-infra (`sim_oil_v2/` itself is explicitly domain-scoped and excluded).

---

## 4. Variable register

### 4.1 Core fundamentals (carry-over from `sim/`)

| Name | Type | Role | Default / notes |
|---|---|---|---|
| `chi_t` | OU, mean 0 | Schwartz-Smith short | κ=2, σ=0.3 |
| `xi_t` | GBM on log-price | Schwartz-Smith long | drift 0, σ=0.08 (annualised) |

Price is still `log_price = χ + ξ + Σ loadings` — but the loadings now come from the new factors below, not from a scalar `balance`.

### 4.2 Inventories (fact 1 + fact 2)

| Variable | Dynamics | Default half-life | Literature |
|---|---|---|---|
| `inv_cushing_t` | OU around regime-dependent mean | 60 days | EIA Cushing stocks series |
| `inv_us_total_t` | OU, slower | 180 days | EIA weekly total US crude |
| `inv_oecd_t` | OU on quarterly cadence | 365 days | IEA OECD commercial stocks |

### 4.3 WTI-Brent regional factor (fact 2)

| Variable | Dynamics | Notes |
|---|---|---|
| `transport_capacity_cushing_t` | Step function with occasional regime-shifts (new pipeline / rail capacity) | Discrete jumps; 2 steps per 10 years in history |
| `brent_risk_premium_t` | Slow OU | Driven by transatlantic shipping proxy |

### 4.4 Spare capacity (fact 3)

| Variable | Dynamics | Notes |
|---|---|---|
| `opec_spare_capacity_t` | OU on 2-year half-life, clipped ≥ 0 | Units: million bbl/day |

### 4.5 Global activity (fact 4)

| Variable | Dynamics | Notes |
|---|---|---|
| `global_ip_t` | Trend-stationary with cycle | Baumeister-Korobilis-Lee: world IP, the best activity indicator |
| `refinery_utilization_t` | Seasonal + OU | Summer driving season peak |

### 4.6 Refining margin (fact 5)

| Variable | Dynamics | Notes |
|---|---|---|
| `gasoline_premium_t` | OU with seasonal overlay + occasional refinery outages (Hawkes-style) | Drives gasoline price above WTI by a time-varying spread |
| `distillate_premium_t` | Similar but winter-weighted | Baumeister-Kilian-Zhou: gasoline spread outperforms 3:2:1 crack |

### 4.7 Producer stress + hedging (fact 7)

| Variable | Dynamics | Notes |
|---|---|---|
| `producer_credit_stress_t` | OU around regime-shifted mean; jumps on stress regime | Proxy: US HY credit spread |
| `speculator_capacity_t` | Inverse of `producer_credit_stress_t` + idiosyncratic noise | Acharya et al.: when producers want to hedge more, speculators have less capacity to take the other side |

### 4.8 Hawkes events (carry-over, but richer)

Events now perturb:
- `inv_cushing_t` mean (disruptions, weather)
- `opec_spare_capacity_t` (OPEC decisions)
- `transport_capacity_cushing_t` (pipeline failures)
- `chi_t` vol (general vol spike)

### 4.9 Regime

| Regime | Dominant dynamics |
|---|---|
| `equilibrium` | Baseline; all factors around stationary means |
| `supply_shock` | `inv_cushing` falls, `opec_spare_capacity` falls, `chi_vol` up |
| `demand_shock` | `global_ip_t` regime-shifted, `refinery_utilization` up |
| `stress` | `producer_credit_stress` high, `speculator_capacity` low (Acharya regime) |

---

## 5. Sign-relationship map (Henri's six sign rules, encoded)

Each rule becomes a loading in the observable-price equation OR a non-linear function in the curve/spread map. No rule is left to the desk models to discover — the sim **generates** data that respects them.

### R-1: Convenience yield ↔ inventory (non-linear)

```
convenience_yield(t) = a - b · log(inv_cushing_t / inv_normal)
                       + non_linear_kink(inv_cushing_t)
```

- For `inv_cushing_t < threshold_low`: convenience yield jumps up (backwardation strengthens rapidly). Steep slope.
- For `inv_cushing_t > threshold_high`: convenience yield bounded at small positive value, curve goes contango.
- Default: threshold_low = 10th %ile of history, threshold_high = 90th %ile.
- Encoded as: `wti_2nd_month - wti_1st_month = -convenience_yield · storage_cost_t`.

**EIA finding**: Cushing inventories are a positive function of the lagged 2nd-minus-1st-month WTI spread — the simulator produces this co-movement by construction.

### R-2: WTI-Brent spread ↔ Cushing + transport

```
wti_brent_spread(t) = α * (inv_cushing_t - inv_normal)
                      + β * (1 - transport_capacity_cushing_t / transport_ref)
                      + brent_risk_premium_t
```

- α < 0, β < 0: high Cushing stocks + low transport capacity → wide WTI discount.
- 2011-13 episode reproducible by setting `transport_capacity_t = 0.6 * transport_ref` for 2 years + elevated `inv_cushing_t`.

### R-3: Spare capacity ↔ price + vol (non-linear)

```
price_risk_premium(t) = γ · max(0, SC_threshold - opec_spare_capacity_t)^2
vol_scaling(t)        = 1 + δ · max(0, SC_threshold - opec_spare_capacity_t)
```

- Quadratic in the deficit below threshold → tail behaviour.
- SC_threshold default: 3 mbd (typical stressed level).

### R-4: Global activity ↔ wti price (linear long-horizon)

```
wti_long_expectation(t, h) = ξ_t + loading_GIP · (global_ip_t - GIP_trend(t))
```

Only affects long-horizon expectation (`h ≥ 6 months`). Short-horizon price doesn't load on GIP (matches Baumeister et al.'s finding that GIP outperforms at long horizons, less so at short).

### R-5: Gasoline-crude spread ↔ future WTI (medium horizon)

```
wti_expectation(t, h=6m..24m) = wti_front(t) + κ(h) · gasoline_premium_t
```

- κ(h) peaks at h=12m, declines above h=24m and below h=3m (matches BKZ's horizon pattern).
- Implementation: the sim emits `E[wti | info_t, h]` curve per day; desks observe the actual realised price at `t + h`.

### R-6: Producer stress ↔ futures premium + inventories (Acharya)

```
futures_premium(t)  = wti_future(t) - wti_spot_expected(t)
                    = μ_premium_baseline + λ · producer_credit_stress_t
                                         - μ · speculator_capacity_t
inv_drift(t)        = baseline_drift - ν · producer_credit_stress_t
```

- Stressed producers hedge more → futures premium up, inventories drained as producers deliver cash commodity → spot depressed.
- Matches Acharya mechanism directly.

### Non-linearity summary

- R-1, R-3 explicitly non-linear.
- R-2, R-4, R-5, R-6 linear within regime, non-linear across regimes via regime-scaled loadings.
- Regime transitions are the discrete non-linearity layer.

---

## 6. Desk mapping

Five forecasting desks + regime classifier, mapped to the five structurally-strongest facts. Fact 2 (WTI-Brent) merges with fact 1 (inventories) because both consume Cushing stocks; fact 6 (futures-first price discovery) is a cross-desk methodological feature implemented at the observation-channel level, not its own desk.

| Phase 3 desk name | Obsolete v1 name | Consumes | Forecasts | Stylised facts |
|---|---|---|---|---|
| `inventories_curve` | storage_curve | `inv_cushing`, `inv_us_total`, calendar spreads, transport_capacity | Next-period `wti_2nd - wti_1st`, `wti_brent_spread` | 1, 2 |
| `spare_capacity` | supply | `opec_spare_capacity`, Hawkes event indicator | WTI risk premium, vol | 3 |
| `global_demand` | demand | `global_ip`, `refinery_utilization`, `inv_oecd` | WTI at 6-24m horizons | 4 |
| `refining_margin` | macro | `gasoline_premium`, gasoline front price | WTI at 6-24m horizons (BKZ horizon pattern) | 5 |
| `producer_flow` | geopolitics | `producer_credit_stress`, `speculator_capacity`, inventories | Futures-premium term structure | 7 |
| `regime_classifier` | (same) | All latent states | Regime label | (cross-cutting) |

**Fact 6 (futures-first)** — implemented as an observation-layer property: `sim_oil_v2/observations.py` emits each desk's price observation from `wti_front_month[t]` (the futures series), with `spot_price[t]` lagged by 1 day. Any desk reading `market_price` gets the futures-forward view. The price-discovery literature is satisfied mechanically rather than via a dedicated desk.

**Target variables registry additions** (append-only to `contracts/target_variables.py`):
- `WTI_2ND_MONTH_CLOSE`
- `WTI_BRENT_SPREAD`
- `WTI_6M_CLOSE`
- `WTI_12M_CLOSE`
- `GASOLINE_FRONT_MONTH_CLOSE`
- `WTI_FUTURES_PREMIUM_3M` (for producer_flow's target)

---

## 7. Non-linearity + regime scaling

Carry over the Phase 1 HMM regime layer (4 states) with tuned dynamics:

| Regime | `inv_cushing` mean | `opec_spare_capacity` mean | `producer_credit_stress` mean | `chi_vol` scaling |
|---|---|---|---|---|
| equilibrium | baseline | 4 mbd | baseline | 1.0 |
| supply_shock | 20% below baseline | 1-2 mbd | baseline | 1.5 |
| demand_shock | 15% above baseline | baseline | baseline | 1.3 |
| stress | 10% below | baseline | baseline × 3 | 2.0 |

Thresholds in R-1 and R-3 remain fixed — non-linearity comes from where the latent state SITS within the regime-shifted distribution, not from regime-contingent thresholds.

---

## 8. Calibration references (one per variable)

Before shipping, pin each variable's default parameters to a literature source:
- `inv_cushing_t` half-life + mean: EIA Cushing historical series (2005-present).
- Cushing ↔ 2nd-1st spread: EIA's reported positive function.
- Brent-WTI decomposition: EIA's storage/transport/Brent-market breakdown.
- `opec_spare_capacity_t` threshold: EIA + IMF "low spare capacity ↔ rising risk premium" work.
- `global_ip_t`: Baumeister, Korobilis, Lee (BVAR forecasting paper).
- `gasoline_premium_t` horizon pattern: Baumeister, Kilian, Zhou (MSPE reductions at h=6..24m).
- Acharya mechanism: Acharya, Lochstoer, Ramadorai (Producer stress → hedging costs → inventory → pricing).
- Non-linearity: Baumeister et al.'s oil-tails paper.

Each parameter comment in the source code includes the citation anchor; reviewers can audit.

---

## 9. Implementation sequence (rough sizing)

Not yet scheduled. Estimated 4–6 weeks of focused work (realistic = 8 weeks per §14.6 escalation risk).

| Week | Deliverable |
|---|---|
| 1 | Package skeleton + `latent_state.py` + 4 inventory/stock variables + regime wiring |
| 2 | Curve construction (`curves.py`) + R-1 encoded + calendar-spread observable |
| 3 | WTI-Brent (`inventories.py` + `locational_basis` logic) + R-2 encoded |
| 4 | Spare capacity + R-3 non-linearity + refining + R-5 horizon pattern |
| 5 | Producer stress + R-6 Acharya mechanism + R-4 global activity |
| 6 | 6 desk refactors + 6 new target_variables + portability-vocab extension + end-to-end multi-scenario test |
| +2 | Calibration reference pinning + spec v3.x write-up + tag `sim-oil-v2-v3.0` |

---

## 10. Interactions with existing debits

| Debit | Effect of sim_oil_v2 ship |
|---|---|
| D1 (Phase A model weakness) | CLOSES for oil — desk models fitting on real stylised-fact signals should pass Gate 1/2 without the ridge-on-generic-OU debit |
| D7 (Phase 2 equity-VRP model weakness) | Unchanged — separate domain |
| D8 (same-target aggregation) | Partially closes — multiple target variables (WTI 1m vs 2m vs 6m) reduce same-target overlap |
| D9 (Gate 3 fake-controller) | Must close BEFORE sim_oil_v2 starts. Gate 3 runtime harness is a prerequisite, not a deliverable of this plan |
| D10 (sim does not encode oil stylised facts) | CLOSES by construction |

---

## 11. Verification

Beyond the per-desk Gate 1/2/3 pass requirements, sim_oil_v2 earns its keep if:

1. **R-1 to R-6 empirically hold in generated data.** Six dedicated tests, one per sign rule, asserting the expected correlation sign and (where quantified) magnitude bracket on 10 seeds × 5-year paths.
2. **2011-13 Cushing episode reproducible.** A pinned parameterisation produces a wide WTI-Brent spread + narrowing when transport capacity recovers.
3. **Oil-tails empirically appear.** Over 5000-day paths, the realised return distribution has kurtosis > 6 (vs ~3 for Gaussian) consistent with Baumeister-tails.
4. **Portability tests still pass.** Oil vocab extended; equity-VRP vocab test unchanged; expanded git-diff audit across shared-infra clean.
5. **Existing `sim/` tests still pass** — `sim_oil_v2/` is additive, not a replacement.

---

## 12. Risks

- **R-1 — Scope sprawl.** 14-factor state is a lot more than the current 5-factor. Estimated 4-6 weeks is optimistic; realistic 8-10 (per §14.6 spec-budget realism).
- **R-2 — Calibration is subjective.** Each parameter has literature anchors, but many oil papers disagree on numbers. Pick one anchor per parameter, cite, move on. Do not chase consensus.
- **R-3 — Distribution shift into Phase 3 real data.** If real data shows signs opposite to R-1-R-6 in some subperiod, the sim is wrong for that subperiod. Accept as a calibration debit — the spec framing is "stylised facts", not "truth in all windows".
- **R-4 — Desk renames cascade.** Renaming storage_curve → inventories_curve, supply → spare_capacity etc. touches every test + spec reference + capability_debits entry. Plan ~2 days for the rename alone; schedule as a separate commit before sim_oil_v2 lands.
- **R-5 — D9 must close first.** Runtime-controller Gate 3 harness is a prerequisite. If D9 is still open when this plan starts, pause and ship D9 first.

---

## 13. Alternative: partial ship

If full sim_oil_v2 is out of budget, partial ship options ranked by value:

| Tier | Scope | Weeks | Covers facts |
|---|---|---|---|
| A | Full 14-factor | 6-10 | 1, 2, 3, 4, 5, 6, 7 |
| B | Inventory + curve only (R-1 + R-2 + R-6 via curve) | 3 | 1, 2, 6 |
| C | Spare capacity + inventory (R-1 + R-3) | 2 | 1, 3 |
| D | Refining margin only (R-5) | 1.5 | 5 |

Tier B is the minimum defensible shipment that addresses the "oil is a term-structure instrument" core claim. Anything below B is cosmetic.

---

## 14. References

- EIA — Cushing inventories ↔ calendar spread ↔ contango.
- EIA — Brent-WTI spread decomposition (storage, transport, Brent-market immediacy).
- CME — 2011-13 Cushing-bottleneck historical account.
- IMF — Long-run spare-capacity ↔ price+vol pattern.
- Baumeister, Korobilis & Lee — World IP as the robust activity signal.
- Baumeister, Kilian & Zhou — Gasoline-crude spread horizon MSPE dominance.
- Acharya, Lochstoer & Ramadorai — Producer stress → hedging cost → inventories → pricing.
- Baumeister et al. — Oil non-linearity / tails.
- ECB — Oil-USD not a stable structural law (exclusion justification).
- Singleton — Investor flows: episodic, not foundational (overlay justification).

Full citations to be added at implementation time in `sim_oil_v2/README.md`.

---

## 15. Decision to proceed

This plan is an artefact, not a commitment. Gating the build on:

1. D9 closure (Gate 3 runtime harness).
2. Phase 2 scale-out complete (desks 3-5 landed under the existing sim).
3. Phase 2 Reliability gate run executed (4h soak produces telemetry baseline).
4. An explicit "start Phase 3 sim_oil_v2" decision point with the operator.

Until all four hold, `sim_oil_v2/` stays in this doc.
