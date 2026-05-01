# v2 decision contract

**Status**: D1 paper artefact. Read-only.
**Tag**: `v2-contracts-0.1`
**Scope**: every desk and every family synthesiser in v2.
**Deviation policy**: changes require a typed deviation record under the
(pending) promotion lifecycle; no silent drift.

---

## 1. What this contract is

This document defines the canonical objects a v2 desk and a v2 family
synthesiser must publish to be admissible to the promotion lifecycle. It
replaces the v1 scalar `point_estimate × weight` raw-sum controller
(`controller/decision.py:94-112`), which admits mixed-unit collisions and has
no distributional representation.

A v2 desk may internally use any model class. What it **publishes** must
conform to this contract exactly.

## 2. Forecast object (desk output)

### 2.1 Required fields

```
family            : str    -- e.g. "oil_wti_5d"
desk              : str    -- e.g. "prompt_balance_nowcast"
decision_ts_utc   : ts     -- eligible decision timestamp (UTC)
target_variable   : str    -- e.g. "WTI_FRONT_1W_LOG_RETURN"
target_horizon    : str    -- e.g. "5d"
decision_unit     : str    -- one of {log_return, spread_change, vol_point_change, utility}
quantiles         : float[7]
quantile_levels   : float[7]  -- fixed: [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]
calibration_score : float in [0,1]
data_quality_score: float in [0,1]
valid_until_ts    : ts     -- decision TTL (UTC)
contract_version  : str    -- semver of this contract, e.g. "2.0.0"
distribution_version: str  -- desk-internal model version
prereg_hash       : str    -- SHA-256 of the desk's locked prereg
evidence_pack_ref : str    -- pointer to the promotion evidence bundle
```

### 2.2 Quantile invariants

- `quantile_levels` is fixed at `[0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]`.
  No other grid is admissible in v2.0.
- `quantiles` must be monotonically non-decreasing. A monotonicity violation
  is a hard gate; the desk must abstain rather than publish a non-monotone
  distribution.
- `quantiles[3]` (the 0.50 quantile) is the canonical point estimate for
  Layer-4 shadow-rule evaluation.

### 2.3 Recommended internal model classes

- **Quantile regression** (linear, gradient-boosted, or neural), wrapped with
  **Conformalised Quantile Regression** for finite-sample coverage guarantees.
- **State-space / dynamic-factor** nowcasts emitting quantiles from the
  posterior predictive.
- **Hurdle models** for event desks — the hurdle probability and conditional
  effect combine into a quantile vector before publication.

No desk may publish a point estimate without a distribution.

### 2.4 Calibration score

`calibration_score` is a rolling-window pinball-loss ratio against baseline B0
(EWMA-Gaussian), mapped to `[0, 1]`:

```
calibration_score = clip(1 - QL_desk / QL_B0, 0, 1)
```

computed over the trailing window specified in the desk prereg (default:
260 decision ticks ≈ 1 year).

### 2.5 Data-quality score

`data_quality_score` is the desk's multiplicative product of per-feature
quality multipliers, each in `[0, 1]`:

```
data_quality_score = ∏_feat q_feat(t)
```

where `q_feat(t)` combines freshness, vintage consistency, source-confidence,
and missingness per the v2 data contract. A single feature with `q = 0`
(catastrophic failure) must trip a hard gate, not merely drive the product to
zero.

---

## 3. Action space (family output)

### 3.1 Formal definition

For every family `F` and every eligible decision timestamp `t`:

```
A_F(t) = { b_t ∈ [-1, 1] } ∪ { ABSTAIN }
```

- `b_t ∈ [-1, 1]` is a **target risk budget** as a fraction of the family's
  **reference 5-day risk sleeve** `R_{5d,unit}^$`.
- `b_t > 0` means long exposure; `b_t < 0` means short; `b_t = 0` means
  explicitly no economic exposure.
- `ABSTAIN` is an **operational override**, not an economic action. It means
  "the system declines to update the target exposure at this timestamp
  because the decision is not valid under the data / model / operational
  contract." It is semantically distinct from `b_t = 0`.

### 3.2 Reference risk sleeve `R_{5d,unit}^$`

A family-level constant declared in the family's prereg and the model
inventory (pending D5). For oil v2.0 this is the dollar risk assigned to a
full-scale oil-family exposure over a 5-trading-day horizon, expressed as a
positional-risk unit (e.g. `1σ × 5d` notional at a pre-declared volatility).

### 3.3 Signal-to-risk ratio

The family synthesiser derives `b_t` from its combined predictive
distribution via a signal-to-risk ratio:

```
μ_t           = Q̂_family(0.50)                    -- family median
σ̂_t^pred      = (Q̂_family(0.95) - Q̂_family(0.05)) / (z_{0.95} - z_{0.05})
                or the IQR analogue from (Q̂(0.75) - Q̂(0.25))
s_t           = μ_t / max(σ̂_t^pred, σ_floor)       -- dimensionless strength
c_t, q_t, r_t ∈ [0, 1]                             -- calibration / quality / roll multipliers
b_t           = clip(k · s_t · c_t · q_t · r_t, -1, 1)
```

where `k` is a family-level gain constant declared in the prereg, and
`σ_floor` is a pre-registered minimum predictive dispersion to prevent
division-by-zero pathologies. `σ̂_t^pred` is **predictive uncertainty**; it
must not be conflated with the market-volatility estimate `σ̂_t^mkt` used by
the execution adapter.

### 3.4 Execution-adapter mapping (downstream of this contract)

The execution adapter, not the decision engine, maps `b_t` to a contract
count. For WTI:

```
n_t* = b_t · R_{5d,unit}^$ / (M · P_t · σ̂_t^mkt)
```

with `M = 1000 barrels` (CL) or `M = 100 barrels` (MCL), `P_t` the
front-month price, and `σ̂_t^mkt` the ex-ante 5-day log-return volatility.
Rounding to discrete lots is the execution adapter's responsibility and is
out of scope for the decision contract.

---

## 4. Degradation ladder

A **TTL** (`valid_until_ts`) on every valid decision, plus a four-state
degradation ladder, defines what happens when valid decisions stop arriving
or when the system detects operational failure.

| State | Condition | Target-position behaviour |
|---|---|---|
| Healthy | Recent valid decision; `t ≤ valid_until_ts` | Rebalance to `f(b_t)` |
| Soft abstain | ABSTAIN for `n ≤ n_soft` ticks | **Hold** last valid target; no trade |
| Aged | Beyond TTL or `n > n_soft` | **Decay** position: `p_{t+1} = (1 - λ) · p_t` |
| Hard fail | Critical system / data / replay failure | **Force flat**: `p_{t+1} = 0` |

Parameters `n_soft`, `λ`, and the hard-fail criteria are declared in the
family prereg. For oil v2.0 the defaults are pre-registered as `n_soft = 3
ticks`, `λ = 0.20 per tick`.

### 4.1 PnL accrual during degradation

Mark-to-market, roll cost, carry, and funding continue to accrue **in all
states**, including `ABSTAIN` and `Aged`. There is no "pause" in the ledger.

### 4.2 Hard-gate categories

A `Hard fail` transition is triggered by, at minimum:

| Class | Trigger examples |
|---|---|
| Data | required source missing, not PIT-eligible for `t`, stale beyond TTL, vintage/checksum mismatch, roll-state ambiguity |
| Model | `calibration_score < c_min`, `σ̂_t^pred > σ̂_max`, quantile monotonicity violation, synthesiser disagreement beyond bound |
| Operational | release-calendar incomplete, replay hash mismatch, dependency failure, invalid risk-unit configuration |

Weak-signal conditions (small `|s_t|`, low conviction) must emit `b_t ≈ 0`,
**not** `ABSTAIN`.

---

## 5. Family synthesiser

### 5.1 Combiner

Family-level predictive distributions are produced by a **weighted linear
pool on the CDF**:

```
F_family(y | t) = Σ_k w_{k,t} · F_k(y | t)          -- k indexes contributing desks
w_{k,t}         = calibration_score_k · data_quality_score_k · π_k(regime_t)
                  renormalised over non-abstaining desks k
```

where `π_k(regime_t)` is the regime posterior on desk `k`. At v2.0 and v2.1
the regime model is a **constant-posterior pass-through**: `π_k ≡ 1` for the
single "normal" regime. The interface is reserved; the model activates at
v2.2.

### 5.2 Family-level abstention

The family abstains at `t` if **any** contributing desk trips **any** hard
gate at `t`. This is the `any-hard-gate` rule. Weak signals do not cascade
to family-level abstention.

### 5.3 Log-pool and Fréchet-bound combiners

Disallowed in v2.0. Promotion via either requires an approved deviation from
this contract; neither is admissible by default.

---

## 6. Persisted decision payload

Every family decision event must persist the following record (DuckDB
`family_decisions` table; schema frozen at this contract version):

```json
{
  "contract_version"         : "2.0.0",
  "family"                   : "oil_wti_5d",
  "decision_ts_utc"          : "2026-05-04T21:00:00Z",
  "instrument_spec"          : "WTI front-month under rolling_rule_v1",
  "target_variable"          : "WTI_FRONT_1W_LOG_RETURN",
  "target_horizon"           : "5d",
  "decision_unit"            : "log_return",
  "action_type"              : "target_risk_budget",
  "target_risk_budget"       : 0.42,
  "abstain"                  : false,
  "abstain_reason"           : null,
  "degradation_state"        : "healthy",
  "valid_until_ts"           : "2026-05-05T21:00:00Z",
  "signal_strength"          : 0.61,
  "family_q01"               : -0.025,
  "family_q05"               : -0.0112,
  "family_q25"               : -0.0030,
  "family_q50"               : 0.0084,
  "family_q75"               : 0.0170,
  "family_q95"               : 0.0267,
  "family_q99"               : 0.0400,
  "pred_scale"               : 0.0115,
  "market_vol_5d"            : 0.034,
  "calibration_multiplier"   : 0.88,
  "data_quality_multiplier"  : 0.93,
  "roll_liquidity_multiplier": 1.00,
  "regime_posterior"         : { "normal": 1.0 },
  "hard_gates_passed"        : true,
  "contributing_forecast_ids": ["fct_<sha>_desk1", "..."],
  "prereg_hash"              : "sha256:...",
  "contract_hash"            : "sha256:..."
}
```

`contract_hash` is the SHA-256 of this document at publish time; it is the
link between a decision event and the contract version under which it was
produced.

---

## 7. Forbidden at this contract version

The following are rejected at publish time (desk or synthesiser) and block
promotion:

- Raw aggregation of quantities with different `decision_unit`.
- Desk publishing a point estimate without a quantile vector.
- Desk publishing without a `prereg_hash`.
- `calibration_score` or `data_quality_score` outside `[0, 1]`.
- Non-monotone quantiles.
- Family-level `ABSTAIN` used to encode "no edge". Use `b_t = 0` for that.
- Weak-signal thresholding applied **after** degradation-ladder logic. The
  ladder operates only on validity, not on conviction.
- Promotion evidence derived from `sim_equity_vrp/` or any v1 simulator
  (those are tagged `v1-sim` with zero promotion authority).
