# Regime Classifier — Spec

**Phase**: 1 (final-step deepen) + v1.16 role expansion.
**Status**: Shipped with two paths:
- `GroundTruthRegimeClassifier` for isolation testing.
- `HMMRegimeClassifier` for data-driven regime inference.

**v1.16 role expansion.** The legacy `macro` desk is removed as a standalone
alpha desk per `docs/first_principles_redesign.md`. Macro-beta transmission is
now carried by the regime-conditioning state this classifier emits. No new
inputs are added at the code level — the HMM still fits on market-price
log-returns. The spec change here records that the Controller's regime-
conditional weight matrix (§8.2) is the channel through which macro state
now influences decisions, rather than a separate `macro` desk forecast.
`regime_id` values and the `RegimeLabel` contract are unchanged; the
domain-blind portability property (§14.7) is preserved.

## 1. Output

`RegimeLabel` events (NOT Forecast events). Interface signature differs from
other desks (see `desks/base.py:ClassifierProtocol`).

## 2. Directional claim

Applies to regime **transitions**: "transitions to regime X are associated
with higher forward realised vol". Pre-registration of per-regime directional
claims happens at deepen time, not at stub phase.

Stub: single regime `regime_boot` with P=1.0; no transitions.

## 3. Pre-registered naive baseline

Single-regime classifier (no regime structure). Controller degenerates to
the unconditional weight matrix; must still function (Gate 3 hot-swap).

## 4. Model ladder

1. Zero-shot: N/A (no off-the-shelf oil regime classifier).
2. Shipped classical specialist: adaptive-K Gaussian HMM over market-price log-returns, selecting `K ∈ [2, 6]` by BIC and emitting at most 6 distinct `regime_id` values per §8.5.
3. Future deepen: HDP-HMM / online Bayesian change-point detection if the bounded Gaussian-HMM family proves insufficient.

## 5. Gate-pass plan

- **Gate 1 (skill)**: Regime labels distinguishable from random on a pre-registered held-out period (forward-vol differs across labels p<0.05 under permutation).
- **Gate 2 (sign preservation)**: Directional claim on transitions holds dev-to-test.
- **Gate 3 (hot-swap)**: Replaceable by StubClassifier without breaking the Controller (Controller degenerates to unconditional).

## 6. Inputs

Desk output Forecasts (point estimates + uncertainties) from the other
forecast-emitting desks. **No raw domain data.**

Under the v1.16 roster, the oil-side inputs are the 3 desks (`storage_curve`,
`supply_disruption_news`, `oil_demand_nowcast`) and the equity-side inputs are
`surface_positioning_feedback` plus the planned `earnings_calendar`. The
legacy reference to the `macro` desk's "macro-regime Forecast" is dropped —
macro-regime is an output *of* this classifier, not an input.

This is the domain-blindness property that makes the classifier redeploy to
equity VRP unchanged.

## 7. Internal architecture

Shipped path: bounded Gaussian-HMM via hmmlearn, fit causally on
market-price log-returns and selected by BIC over a capped state-count
range. Future deepen remains HDP-HMM in PyMC or a small custom Gibbs
sampler plus online change-point detection if needed.

## 8. Capability-claim debits

- **Pre-emptive**: Phase 2 equity-VRP redeployment is the acceptance test.
  If the classifier requires any equity-specific features (not just desk
  outputs), the domain-blind claim breaks — that's a portability debit.
