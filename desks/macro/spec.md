# Macro & Numeraire Desk — Spec

**Phase**: 1 (deepen Week 5).
**Status**: Week 1-2 stub only.

## 1. Target variables and horizons

- `wti_front_month_close` @ EventHorizon(eia_wpsr, ~7d) — conditioned on macro regime & USD decomposition.
- Macro regime emitted as a Forecast (NOT RegimeLabel — that's the classifier's sole role per §10.1).

## 2. Directional claim

**Negative** on `wti_front_month_close` wrt `rates_driven_dxy_move` (rates-driven USD rally compresses oil).
**Negative** on `wti_front_month_close` wrt `risk_off_flight_to_quality` (risk-off USD rally with weaker activity).

Stub: sign = "none".

## 3. Pre-registered naive baseline

Unconditional mean of forward `wti_front_month_close` over trailing dev window.

## 4. Model ladder

1. Zero-shot: TabPFN-v2 for cross-asset sensitivities.
2. Classical specialist: Mixed-frequency BVAR (same architecture as Demand desk, different variables); Markov-switching regression for regime classification; HMM latent-state inference; online Bayesian change-point detection (Adams-MacKay 2007); factor model (PCA + regression on macro surprises) for DXY decomposition.
3. Fine-tune: rarely; macro is well-served by classical tooling.

## 5. Gate-pass plan

- **Gate 1 (skill)**: Beat unconditional-mean baseline on test RMSE.
- **Gate 2 (sign preservation)**: Signed macro-regime Spearman correlation with forward realised vol preserves direction dev→test.
- **Gate 3 (hot-swap)**: Replaceable by StubDesk.

## 6. Data sources

- FRED (US macro indicators, free)
- TIPS / breakeven inflation series (FRED)
- DXY, EUR/USD, JPY/USD (Yahoo Finance / Stooq, free)
- Google Trends

All free / public.

## 7. Internal architecture

TBD.

## 8. Capability-claim debits

None at stub phase.

## 9. Phase 2 readiness checkpoint (§14.7)

Macro is the Week 5 / Month-5 checkpoint desk. During this desk's deepening,
confirm five equity-VRP desk candidates exist in the Speckle and Spot
project (or explicitly open). Missing by month 5 = capability-claim debit
on Phase 2 timeline.
