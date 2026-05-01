# v2.0 WTI track — pre-registered stop conditions

**Status**: DRAFT for operator review. Not yet authoritative. No D-decision filed.
**Created**: 2026-04-27
**Scope**: v2.0 oil family + `prompt_balance_nowcast` desk only. Each later v2.x track
declares its own stop conditions when it opens.

## Why this document exists

§5.1 acceptance criteria define what *passes* promotion. They do not define what triggers
*abandonment* of v2.0. Without a written abandonment criterion the project can drift into
indefinite mechanism-isolation work — adding features, then changing model class, then
swapping target horizon — without ever conceding the track has failed. This document
makes the abandonment threshold explicit and auditable.

The principle: **if every named mechanism has been ruled in or out and the cost-adjusted
result still does not beat the empirical baseline, the track ends.** The architecture
machinery (contracts, bus, controller, attribution, evaluation harness) is the deliverable
and is not in scope for these stop conditions; only the v2.0 *modelling track* is.

This document is consistent with §1.3.4 (negative results are deliverables) and the
HOLD-default revision of 2026-04-25.

## Hard stops (any one triggers a freeze decision)

A freeze decision means: pause feature/model work on the v2.0 oil family, write a
post-mortem, and require operator authorisation to reopen. It does not mean the
repo is archived or the architecture is invalidated.

1. **Mechanism budget exhausted without promotion.** All four currently-named
   mechanism tests (H1 σ-calibration, H2 distribution shape, H4 horizon, H5 upstream
   features) have completed and *no* configuration produces:
   - `model_pinball_loss < empirical_pinball_loss` *and*
   - `model_crps < empirical_crps` *and*
   - cost-adjusted (`cost_projection_pessimistic.net_return_total > 0`)
   on at least one of `h ∈ {1, 2, 5, 10}` days.

2. **Cost-adjusted return is structurally negative.** Any model class that beats both
   distributional baselines on pinball **but** produces
   `cost_projection_pessimistic.net_return_total ≤ 0` after H1+H2 are resolved is a
   capability signal for the architecture (§1.3.2) but not a v2.0 promotion candidate.
   Two such confirmations in a row across distinct model classes triggers freeze.

3. **Three model classes fail.** Ridge (already fails), one foundation model trial
   (e.g. Chronos-2 zero-shot), and one structured alternative (e.g. quantile regression
   or conformalised prediction) all fail criterion 1 above with the same upstream
   feature stack.

4. **Architectural debit count rises above three concurrent open D-debits** that block
   v2.0 phase exit (per `docs/capability_debits.md` budget rules). Continued feature
   work cannot reduce this; only operator triage can.

5. **PIT or leakage breach** that is not closable by a one-commit fix. A leakage gate
   regression that requires reshaping the feature view or PIT store schema indicates
   the substrate is wrong for the track and must be revisited before more model work.

## Soft stops (require an explicit go-decision before continuing)

Soft stops do not freeze the track but require an in-writing decision (D-entry in
`raid_log.md`) before adding more features or attempting another model class.

- **Coverage breach.** Empirical `coverage_80` outside [0.65, 0.90] or `coverage_95`
  outside [0.85, 0.99] across the full walk-forward decision sequence. Indicates
  systematic mis-calibration that needs to be diagnosed before more feature work.
- **Centre-forecast collapse.** `centre_forecast_std / realised_abs_return_mean < 0.10`
  (current S4-3: 0.0104 / 0.0397 ≈ 0.26 — close to this threshold). Signals the
  centre carries no usable information; further work should target distribution
  shape, not point predictions.
- **Sigma-ratio drift.** `sigma_ratio_residual_to_target_mean` outside [0.5, 1.5].
  Signals σ-calibration is broken in a way that overwhelms other mechanisms; H1-style
  σ patches must precede further work.
- **Spec drift.** Two spec revisions (v2.0.x bumps) within a 14-day window without an
  operator-signed gate, or any v2.x bump triggered to accommodate a single failing
  experiment.

## Pre-registered values to compare against (frozen 2026-04-27)

These are the current S4-3 measurements on `data/s4_0/free_source/raw/DCOILWTICO.csv`,
9381 walk-forward decisions, 5-day forward log return, ridge alpha 10.0:

| Quantity | Value | Source |
|---|---:|---|
| `model_pinball_loss` | 0.0101535604 | `v2/s4_0/model_quality.py` |
| `empirical_pinball_loss` | 0.0099992225 | same |
| `zero_gaussian_pinball_loss` | 0.0100873280 | same |
| `directional_accuracy` | 0.5077 | same |
| `coverage_80` | 0.8759 | added 2026-04-27 |
| `coverage_95` | 0.9567 | added 2026-04-27 |
| `sigma_ratio_residual_to_target_mean` | 0.9857 | added 2026-04-27 |
| `centre_forecast_std` | 0.01037 | added 2026-04-27 |
| `realised_abs_return_mean` | 0.03970 | added 2026-04-27 |
| `cost_projection_pessimistic.gross_return_total` | +2.291 | added 2026-04-27 |
| `cost_projection_pessimistic.cost_total` | 10.562 | added 2026-04-27 |
| `cost_projection_pessimistic.net_return_total` | **−8.271** | added 2026-04-27 |

Pinned `result_hash`: `4d3a6b333e05ab663175fa4b8e5d56f18bbf72ac2575575c705d1bab138d1315`.

## What is NOT a stop condition

These are *capability debits*, not stop triggers:

- A single failing model class (the ridge in S4-3 is one).
- A single mechanism test failing to isolate its variable.
- Direction accuracy at 50.77%; pinball is the layer-3 metric, not directional.
- A widened coverage gap that is monotone-improving across mechanism tests.
- A specific feature ingester (CFTC, EIA) failing — substrate is replaceable.

## Review cadence

This document is reviewed by the operator at the close of each S4-3 mechanism test (H1
done; H2, H4, H5 pending). Numerical thresholds may be revised pre-test but never
post-test on the same data. Any threshold revision must be a separate D-entry with a
written rationale.

## Operator authorisation

This draft is **not** the authoritative version until the operator signs a D-decision
in `docs/pm/raid_log.md` accepting the criteria. Until then, no model/feature work
should be terminated solely by reference to this document.
