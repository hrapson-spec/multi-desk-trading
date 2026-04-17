# Storage & Curve Desk — Spec

**Phase**: 1 (deepen Week 3, **first real-deepen** per plan §12.1).
**Status**: Week 1-2 stub only.

## 1. Target variables and horizons

- `wti_front_month_close` @ EventHorizon(cftc_cot, ~7d) — weekly cadence aligned to CFTC COT release.
- Additional targets (calendar-spread m1-m2, realised vol) added via v1.x registry additions as they come online.

## 2. Directional claim

**Positive** on `wti_front_month_close` wrt managed-money positioning extremes (contrarian — extremes mean-revert).

Stub: sign = "none".

## 3. Pre-registered naive baseline

Random walk on `wti_front_month_close` (one-week horizon).

## 4. Model ladder

1. Zero-shot: Kronos-small (~25M params, ~1-2GB Q4 inference on 8GB). Output: tail-ES forecasts on a 5-day horizon.

   **Kronos integration is the load-bearing v1.x addition on this desk.** Lessons from prior Kronos V2 work (see `docs/reviews/` for related RCA via the spec's derivation trace): the clip-censoring failure mode that sank the previous integration is mitigated here by (a) percentile-mapped calibration instead of fixed-ratio-to-dev-median, (b) the sign-preservation gate forcing dev-to-test verification before any promotion.

2. Classical specialist: CatBoost on CFTC disaggregated COT features + Dynamic Nelson-Siegel level/slope/curvature factors + functional change-point detection on curve regime shifts.

3. Fine-tune: borrowed-compute only if zero-shot Kronos + classical specialist both fail skill.

## 5. Gate-pass plan

- **Gate 1 (skill)**: Beat random walk RMSE on `wti_front_month_close` for one-week horizon on test.
- **Gate 2 (sign preservation, HARD)**: Pre-registered Spearman(q = percentile-mapped Kronos tail-score, forward realised 20-day vol) positive on both dev and test. Sign-flip = retire desk (Kronos V2 RCA lesson).
- **Gate 3 (hot-swap)**: Replaceable by StubDesk or by classical-specialist sibling without breaking the Controller.

## 6. Data sources

- WTI OHLC (free: Yahoo Finance, Stooq, or EIA spot series).
- CFTC COT disaggregated (free, Fridays 15:30 ET).
- OPEC MOMR text (free).

No paid feeds.

## 7. Internal architecture

TBD — integration details at deepen phase.

## 8. Capability-claim debits

- **Pre-emptive**: Kronos V2 previously failed as a multiplier-scaled integration. The percentile-mapped calibration approach is untested in production at this repo. If Gate 2 fails under the new calibration, the classical-specialist fallback applies (debit: "Kronos zero-shot insufficient with percentile-mapping; fallback to CatBoost+DNS").
