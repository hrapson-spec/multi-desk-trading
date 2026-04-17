# Storage & Curve Desk — Spec

**Phase**: 1 (deepen Week 3, **first real-deepen** per plan §12.1).
**Status**: Classical-specialist prototype landed (Week 3 deepen, pipeline
validation). Zero-shot Kronos slot still open.

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
- **Gate 2 (sign preservation, HARD)**: Pre-registered directional claim is
  positive Spearman(score, forward realised outcome) on both dev and test,
  where `score` is:
  - For the Kronos-zero-shot path: percentile-mapped Kronos tail-score vs forward realised 20-day vol.
  - For the classical-specialist path (current): signed predicted log-return over the horizon vs realised log-return.
  Sign-flip = retire desk (Kronos V2 RCA lesson).
- **Gate 3 (hot-swap)**: Replaceable by StubDesk or by classical-specialist sibling without breaking the Controller.

### Landed artefacts (Week 3 deepen)

- `desks/storage_curve/classical.py` — `ClassicalStorageCurveModel`: ridge over (last-return, mean-return, return-vol, return-trend). Fits on log-return horizon target; predicts price via `current_price · exp(predicted_log_return)`.
- `desks/storage_curve/desk.py` — `StorageCurveDesk(model=...)` emits positive-signed Forecasts with `staleness=False` when a fitted model is supplied; falls back to stub when model is absent or feature window underflows.
- `tests/test_storage_curve_gates.py::test_storage_curve_classical_passes_all_three_gates_on_ar1` — end-to-end pipeline verification on a synthetic AR(1) path. Illustrative numbers (seed 11, horizon 3, AR(1)=0.9, vol=0.01, lookback=10, α=1): Gate 1 +8.99% RMSE vs random walk; Gate 2 ρ_dev=+0.70, ρ_test=+0.64; Gate 3 pass.

## 6. Data sources

- WTI OHLC (free: Yahoo Finance, Stooq, or EIA spot series).
- CFTC COT disaggregated (free, Fridays 15:30 ET).
- OPEC MOMR text (free).

No paid feeds.

## 7. Internal architecture

TBD — integration details at deepen phase.

## 8. Capability-claim debits

- **Pre-emptive**: Kronos V2 previously failed as a multiplier-scaled integration. The percentile-mapped calibration approach is untested in production at this repo. If Gate 2 fails under the new calibration, the classical-specialist fallback applies (debit: "Kronos zero-shot insufficient with percentile-mapping; fallback to CatBoost+DNS").
- **Week 3 prototype**: classical specialist is landed as ridge-over-price-features, not CatBoost+COT as the spec envisioned. Reasons: (a) synthetic-only regime §1.2 has no COT data to ingest, (b) CatBoost is not in the dependency set, (c) goal of this step is pipeline validation (fit → predict → emit Forecast → grade → Gate runner), not alpha on real crude. The full CatBoost + Dynamic Nelson-Siegel integration remains a v1.x deepen item and is blocked on real-data ingest work.
