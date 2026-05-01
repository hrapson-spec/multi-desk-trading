# v2 model inventory

**Status**: D5 paper artefact. Read-only.
**Tag**: `v2-inventory-0.1`
**Purpose**: single source of truth for every v2 model, its owner, its
validator, its state, its approval expiry, its monitoring thresholds, and
its incident history.

This file is **manually curated**. Updates are part of the same commit
that changes a desk's state, expiry, or thresholds. Machine-readable
mirrors live in `v2/governance/persistence.py` tables (pending Phase B).

---

## 1. Inventory schema

Each row (family / desk / model class) declares:

```
family                 : str
desk                   : str | "*"           -- "*" = family-level synthesiser
model_class            : str
current_state          : S0..S6 | pending
current_approval_expiry: date | "n/a"
latest_validation_run  : id | "—"
owner_role             : "operator"          -- solo-operator constant at v2.0
validator_role         : "operator_time_separated" | "external:<name>"
monitoring_thresholds  : { c_min, sigma_max, ... }      -- cited from prereg
active_incidents       : list[incident_id]
approval_history       : [ { state, ts, validation_run_id }, ... ]
retirement_plan        : "none" | brief description
notes                  : free text
```

---

## 2. v2.0 inventory (initial population)

### 2.1 Family: `oil_wti_5d`

| Field | Value |
|---|---|
| Instrument | WTI front-month future under `rolling_rule_v1` |
| Decision unit | `log_return` |
| Target variable | `WTI_FRONT_1W_LOG_RETURN` |
| Horizon | 5 trading days |
| Reference risk sleeve `R_{5d,unit}^$` | **pending** — declared in the family prereg |
| Current state | S0 (concept) |
| Owner | operator |
| Validator | operator_time_separated (routine); external for S5 (not in v2 scope) |
| Synthesiser class | weighted_linear_pool_on_cdf |
| Regime model | constant_posterior (interface reserved for v2.2 activation) |
| Incidents | — |

#### 2.1.1 Desk: `prompt_balance_nowcast`

| Field | Value |
|---|---|
| Model class | `dynamic_factor_nowcast_v1` (candidate) |
| Current state | S0 |
| Features (candidate set; locked at prereg) | `eia_crude_stocks`, `eia_gasoline_stocks`, `eia_distillate_stocks`, `refinery_runs`, `crude_imports`, `crude_exports`, `wti_calendar_spread_1_2` |
| Training window | **pending Layer-1 PIT audit** |
| Monitoring thresholds (candidates) | `c_min = 0.55`, `σ̂_max = 0.08 (5d log-return)`, `N_cal = 10`, `N_sigma = 10`, `n_soft = 3`, `λ = 0.20` |
| Approval expiry | n/a |
| Latest validation run | — |
| Retirement plan | none |
| Notes | v2.0 first-desk target. Layer-1 audit blocks all forward motion. |

### 2.2 Deferred desks (not yet at S0)

| Desk | Target family | Earliest version | Notes |
|---|---|---|---|
| `oil_disruption_event` | `oil_wti_5d` | v2.1 | Hurdle model. Blocked on v2.0 S4 stability. |
| `oil_cross_asset_transmission` | `oil_wti_5d` | v2.2 | Regime-conditional. Activates regime model. |
| `vix_surface_state` | `equity_vrp_vix_3d` | v2.3 | First equity-vol desk. Requires new family prereg. |
| `vix_scheduled_catalyst` | `equity_vrp_vix_3d` | v2.4 | Earnings + FOMC event-study model. |

### 2.3 Frozen / retired (v1)

| Artefact | Status | Notes |
|---|---|---|
| `controller/decision.py` raw-sum controller | **scheduled deletion at v2.0 S2→S3** | Violates the v2 decision contract. |
| `desks/{storage_curve, oil_demand_nowcast, supply_disruption_news, surface_positioning_feedback, earnings_calendar, regime_classifier}` | **scheduled deletion at v2.0 S2→S3** | Replaced by v2 desks; mechanisms were not identifiable per the v2 contract. |
| `sim_equity_vrp/`, `sim_oil/` (if any) | **tag `v1-sim` post-v2.0 S3** | Retained as software / fault-injection testbed only. Zero promotion authority per `docs/v2/promotion_lifecycle.md §11`. |
| `eval/` (v1 gate pack) | **scheduled deletion at v2.0 S2→S3** | Replaced by `v2/eval/`. |

---

## 3. Monitoring (per-desk)

At every decision tick the paper-live loop records, per desk:

| Metric | Threshold | Action on breach |
|---|---|---|
| `calibration_score` trailing-260-tick | `< c_min` for `N_cal` ticks | rule KS-M01 → desk_isolated |
| `pred_scale` (σ̂_pred) | `> σ̂_max` for `N_sigma` ticks | rule KS-M02 → desk_isolated |
| `data_quality_score` | `= 0` | rule KS-D01 → desk_isolated |
| quantile monotonicity | violated | rule KS-M03 → desk_isolated + sev2 |
| synthesiser disagreement (family) | beyond bound for `N_syn` | rule KS-F02 → family frozen |

Thresholds for each active desk are authoritatively declared in its
prereg and mirrored into this inventory on every promotion.

---

## 4. Incident history

Append-only table; one row per incident. v2.0 entries:

| incident_id | opened_at | scope | severity | status | closure_evidence |
|---|---|---|---|---|---|
| — | — | — | — | — | — |

---

## 5. External reviewers

Reserved for S5+ promotions. No reviewer engaged at v2.0. Budget and
selection process per `docs/v2/governance_model.md §5`.

---

## 6. Forbidden

- Changing monitoring thresholds in this file without a matching prereg
  update + validation run.
- Promoting any desk without updating `approval_history` in the same
  commit.
- Listing a desk's state as S2+ without a `latest_validation_run`
  reference.
- Treating this document as the authoritative source for prereg values;
  the prereg YAML files are authoritative, this inventory is a summary
  for operator review.
