# Feasibility Harness v1 Baseline — Tractability Gate (WPSR-only)

Created: 2026-04-29
Schema: `tractability.v1.0`

## Verdict (Phase 0)

- Rule: `continue_small_model_only`
- Action: `remove_foundation_models_from_harness`
- min_effective_n (Phase 0): **163**

The v0 finding is preserved: 163 effective post-2020 WPSR-conditioned events
on a 5d/5+5 regime supports small-model-only continuation.

## What v1 adds over v0

1. **§6 HAC effective-N implemented** (Newey-West + Bartlett kernel,
   per-lag autocorrelation lower-bounded at 0). Phase 0 reports it as a
   diagnostic only (see B8 below); Phase 3+ will propagate it into
   `n_star`.
2. **§6 block-bootstrap variance-ratio implemented** (circular block
   bootstrap, block_length = max(spec_lower_bound, 5), B = 2000).
3. **§12-compliant manifest** — every mandatory field is populated.
   Placeholders are explicit (`n_oos_by_fold = {}`,
   `n_by_regime = {"unknown": ...}`).
4. **Vintage-quality filter** at the family level. PIT manifest currently
   has 3924 rows all `true_first_release`; zero rejections.
5. **Multi-family registry** — adding STEO / EIA-914 / OPEC ministerial /
   FOMC families is now a single-line registry change in
   `feasibility/tractability_v1.py`.

## Per-target results

| Target | N_post_embargo | HAC NW | Block bootstrap | Phase-3 strict N_star |
|---|---:|---:|---:|---:|
| `wti_5d_return_sign` | 163 | 147 | 150 | 147 |
| `wti_5d_return_magnitude` | 163 | **66** | 67 | **66** |
| `wti_5d_mae_conditional` | 163 | 160 | 163 | 160 |

The magnitude target shows severe autocorrelation (volatility clustering in
WTI returns). If a Phase 3+ candidate validates on raw magnitude, its
effective sample size will be ~66, well below the spec's 100 stop-gate.
This is a **pre-warning for any future Phase 3 candidate that emits
magnitude predictions**: it must improve over baseline by a substantially
larger margin than the post-embargo MDE table suggests.

## Spec issue B8 — discovered during v1 build

Spec §1 defines `N_star = min_target(N_eff_oos_post2020_pit_clean_target_realizable_purged_embargoed_costed)` — no `hac_adjusted` suffix.

Spec §6 defines `N_eff = floor(min(N_after_purge_embargo, N_eff_hac))` — explicit HAC term.

Spec §9 phase gates use `N_eff_oos_post2020`, which by §6 includes HAC.

The two are reconcilable only if "validation score series" in §6 is
interpreted as **post-modelling residuals or per-event skill scores**,
which do not exist at Phase 0 tractability.

**Phase 0 disposition adopted in v1:** HAC and block bootstrap are
computed on the *raw target* series and reported in
`n_hac_or_block_adjusted_by_target` as Phase-3-readiness diagnostics, but
they do not enter `n_star`. The `n_star_strict_hac_phase3plus` field
captures what a strict §6 reading would yield, surfacing the magnitude
target's 66-event ceiling.

**Recommended spec amendment** for `n_requirement_spec_v1.md`: add to §6:

> "At Phase 0 (tractability), there is no validation score series. HAC
> effective-N is reported on the raw target series as a Phase-3-readiness
> diagnostic only and is not propagated into N_star. From Phase 3 onward,
> HAC is computed on the validated model's per-event skill score or
> residual series and is propagated into N_star per the formula above."

## Files

- Harness: `feasibility/tractability_v1.py` (~920 LOC including tests; 23 tests pass — 5 v0 + 18 v1).
- Manifest: `feasibility/outputs/tractability_v1_baseline_wpsr_only.json`.
- Tests: `tests/feasibility/test_tractability_v1.py`.

## Reproducibility

```
cd multi-desk-trading
.venv/bin/python -m feasibility.tractability_v1 \
    --output feasibility/outputs/tractability_v1_baseline_wpsr_only.json
.venv/bin/pytest tests/feasibility/ -v
```

Same git commit on the same PIT manifest produces a byte-identical JSON
(modulo `created_at_utc` and `git_commit`).
