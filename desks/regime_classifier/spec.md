# Regime Classifier — Spec

**Phase**: 1 (final-step deepen).
**Status**: Week 1-2 stub only. Always emits regime_boot.

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
2. Classical specialist: Hierarchical Dirichlet process HMM (HDP-HMM), non-parametric regime count, capped to max 6 distinct regime_ids at emission time per §8.5. Online Bayesian change-point detection (Adams-MacKay 2007) for fast-break identification.
3. Fine-tune: N/A.

## 5. Gate-pass plan

- **Gate 1 (skill)**: Regime labels distinguishable from random on a pre-registered held-out period (forward-vol differs across labels p<0.05 under permutation).
- **Gate 2 (sign preservation)**: Directional claim on transitions holds dev-to-test.
- **Gate 3 (hot-swap)**: Replaceable by StubClassifier without breaking the Controller (Controller degenerates to unconditional).

## 6. Inputs

Desk output Forecasts (point estimates + uncertainties) from the other five
desks, plus the Macro desk's macro-regime Forecast. **No raw domain data.**

This is the domain-blindness property that makes the classifier redeploy to
equity VRP unchanged.

## 7. Internal architecture

HDP-HMM in PyMC or a small custom Gibbs sampler; online change-point in
numpy. Both run local on 8GB M-series.

## 8. Capability-claim debits

- **Pre-emptive**: Phase 2 equity-VRP redeployment is the acceptance test.
  If the classifier requires any equity-specific features (not just desk
  outputs), the domain-blind claim breaks — that's a debit on the portability
  target.
