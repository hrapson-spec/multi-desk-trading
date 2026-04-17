# Supply Desk — Spec

**Phase**: 1 (deepen Week 5-10 parallel with Demand).
**Status**: Week 1-2 stub only. Full implementation is a v1.x addition.

## 1. Target variables and horizons

- `wti_front_month_close` @ EventHorizon(event_id="eia_wpsr", ~7 days)
- Additional targets (global oil production, per-basin production) deferred until ingestion plumbing exists.

## 2. Directional claim

**Positive** on `wti_front_month_close` with respect to `abs(supply_shock_es95)`.

Rationale: larger supply shocks (in absolute terms) should align with higher forward realised volatility. Dev-period Spearman to be verified before deployment sign-off.

Stub pre-deployment: sign = "none" (explicitly non-claiming; exempted from sign-preservation gate during stub phase).

## 3. Pre-registered naive baseline

Random walk (persistence of last WPSR print). Desk's forecast must beat RMSE of `value[t] = value[t-1]` on test.

## 4. Model ladder (spec §7.3)

1. Zero-shot: Salesforce MOIRAI-2 small variant (~70M params), local-inference-feasible on 8GB M-series.
2. Classical specialist: CatBoost on structured features (rig counts, field decline, OPEC quota compliance).
3. Borrowed-compute fine-tune: only if both 1 and 2 fail Gate 1 skill.

Structural identification layer: Bayesian SVAR with Kilian-Murphy sign restrictions, extended with Antolín-Díaz & Rubio-Ramírez narrative restrictions. Consumes identified shocks rather than raw prices.

## 5. Gate-pass plan

- **Gate 1 (skill)**: RMSE on test beats random walk on `wti_front_month_close` EIA-WPSR forecast.
- **Gate 2 (sign preservation)**: Spearman(q = directional score, forward realised vol) positive on both dev and test, |ρ| ≥ 0.20 on dev.
- **Gate 3 (hot-swap)**: Replaceable by `StubDesk` without breaking the Controller.

## 6. Data sources

- EIA-914 (monthly US crude production)
- EIA WPSR (weekly petroleum status report)
- OPEC MOMR (monthly, text-parsed)
- JODI (crude export/import/storage)
- CFTC COT (positioning, context)

All free / public per §1.2. No paid feeds.

## 7. Internal architecture

TBD. See plan §12.1 Week 5-10 build window.

## 8. Capability-claim debits

None at stub phase.
