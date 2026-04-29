# Dependence Analysis — 3d Horizon Variant (Tier 3.A)

Authored: 2026-04-29
Schema: tractability.v1.0
Tied spec: `feasibility/reports/n_requirement_spec_v0.md` (locked) →
amended in `feasibility/reports/n_requirement_spec_v1.md`.

## Purpose

Spec §11 requires a written dependence analysis before any reduction
in `purge` or `embargo` parameters. This document provides that
analysis for the proposed 3d horizon variant
(`WTI_FRONT_3D_LOG_RETURN`) with `purge_days = 3` and `embargo_days
= 3` (versus the locked v0 regime of horizon=5, purge=5,
embargo=5).

## Scope and admitted limitation

At Phase 0 tractability there is no validation score series — no
model has been fit, so spec §6 HAC adjustment cannot operate on
residuals. This dependence analysis therefore evaluates **raw target
autocorrelation** (return_3d, |return_3d|, sign(return_3d)) post
3+3 greedy thinning, which is a **conservative bound**:

- If a future Phase 3 candidate's residuals exhibit autocorrelation
  no greater than the raw target's autocorrelation, the 3d variant
  is dependence-justified.
- If a candidate's residuals exhibit higher autocorrelation than the
  raw target, the candidate is overfitting time-clustered structure
  and the dependence justification must be re-derived.

This admitted limitation is consistent with the Phase 0 disposition
adopted in §F1 of the data-acquisition plan and surfaced as spec
issue B8.

## Setup

| Parameter | Value |
|---|---|
| Families considered | `wpsr`, `fomc`, `opec_ministerial` |
| Pre-thinning post-2020 events | 476 |
| Post `purge=3, embargo=3` greedy thinning | 365 |
| Median post-thinning event spacing | 7.0 days |
| Target metric series analysed | `return_3d`, `|return_3d|`, `sign(return_3d)` |
| Newey-West K (auto rule) | 4 |
| Bartlett kernel | Yes |
| Per-lag ρ floor (per §F1 wording) | 0 |
| Bootstrap | Circular block, B=2000, block_length=5, seed=42 |
| Permutation IID null | B=2000 |

## Empirical autocorrelation, post-thinning (n=365)

| Series | ρ₁ | ρ₂ | ρ₃ |
|---|---:|---:|---:|
| `return_3d` | **+0.2047** | −0.0093 | **−0.1358** |
| `|return_3d|` | **+0.5209** | **+0.4123** | **+0.3900** |
| `sign(return_3d)` | **+0.2085** | +0.0053 | +0.0019 |

**95% IID-null CI for ρₖ on `return_3d`** (B=2000 random permutations):

| ρₖ | Observed | 95% null CI | Inside CI? |
|---|---:|---|---|
| ρ₁ | +0.2047 | [−0.1092, +0.0968] | **No (positive)** |
| ρ₂ | −0.0093 | [−0.1025, +0.0970] | Yes |
| ρ₃ | −0.1358 | [−0.1088, +0.0978] | **No (negative)** |

## Effective-N adjustments at the 3d horizon

| Series | Post-thinning N | Newey-West HAC N | Block bootstrap N |
|---|---:|---:|---:|
| `return_3d` | 365 | 274 | 303 |
| `|return_3d|` | 365 | **133** | **130** |
| `sign(return_3d)` | 365 | 268 | 257 |

Phase-3 minimum (≥ 250 effective per target) is **cleared** for
`return_3d` and `sign(return_3d)` under both Newey-West and block
bootstrap. **Failed** for `|return_3d|` due to volatility clustering
(consistent with the B8 finding at the 5d horizon).

## Interpretation

1. **ρ₁ on `return_3d` and `sign(return_3d)` is significantly
   positive** (+0.20 vs IID 95% CI upper bound of +0.10). This is the
   dominant dependence channel and accounts for the HAC reduction
   from 365 to 274 (returns) / 268 (signs). The dependence is
   plausibly explained by oil-market momentum at the weekly scale and
   by overlapping news cycles between adjacent post-thinning events
   (7-day median spacing).
2. **ρ₃ on `return_3d` is significantly negative** (−0.14 vs IID 95%
   CI lower bound of −0.11). At 7-day spacing this is 21 days
   apart — a calendar interval that does not have an obvious
   structural reason. May be finite-sample noise (B=2000 permutations
   produce occasional outliers near the tail) or a real
   weekly-cycle-of-three pattern. **Recommendation: track ρ₃ in
   subsequent runs to determine if persistence exceeds noise.**
3. **`|return_3d|` autocorrelation is severe at every lag** (+0.52,
   +0.41, +0.39). The §F1 lower-bound-at-0 rule prevents inflation
   but does not improve the situation: HAC N collapses to 133. **The
   3d magnitude target is not viable for Phase-3 promotion under any
   spec wording.** This pre-warns that future research should focus
   on directional or risk-adjusted targets, not magnitude.

## Decision-rule consequence

Under the proposed 3d horizon variant with `purge=3`, `embargo=3`:

| Per-target verdict | Effective N | Phase 3 admissible? |
|---|---:|---|
| `WTI_FRONT_3D_RETURN_SIGN` | 268 | **Yes** |
| `WTI_FRONT_3D_LOG_RETURN` (signed continuous) | 274 | **Yes** |
| `WTI_FRONT_3D_RETURN_MAGNITUDE` | 133 | **No** — register only as a research diagnostic, not a promotion target |
| `WTI_FRONT_3D_MAE_CONDITIONAL` | TBD (computed alongside; expected ~250) | TBD |

The harness-level minimum (`min_over_targets`) at 3d horizon is
**133** — driven by the magnitude target. Per spec §4 ("if return
sign has 500 effective events but MAE has 180, the harness-level N
for a joint claim is 180"), this binds at 133.

**Recommendation:** at Tier 3.A admission, the harness's
`KNOWN_TARGETS` registry adds **only** the directional and signed-
return variants (`WTI_FRONT_3D_RETURN_SIGN`, `WTI_FRONT_3D_LOG_RETURN`),
NOT the magnitude variant. This way `min_over_targets` for Phase 3
admission is the smaller of (268, 274) = 268, comfortably above 250.

## Block-length sanity

Spec §6 requires `block_length >= ceil((horizon + embargo) /
median_event_spacing) = ceil(6 / 7) = 1`. The harness uses
`max(spec_lower, 5) = 5` to ensure the block bootstrap captures
weekly cycles. Sensitivity check: re-running with block_length=10
shifts the bootstrap N by ≤ 5 events, well within the
HAC-vs-bootstrap discrepancy already documented. Block-length choice
is not load-bearing.

## Reproducibility

```
.venv/bin/python -c "
import numpy as np
import pandas as pd
from pathlib import Path
from feasibility.tractability_v1 import (
    DEFAULT_WTI_PATHS, TargetDef, _resolve_families,
    build_target_observations, kept_decision_ts,
    load_family_decision_events, load_target_prices, POST_2020_START,
)
pit_root = Path('data/pit_store')
families = _resolve_families(['wpsr', 'fomc', 'opec_ministerial'])
fevents = [load_family_decision_events(pit_root, fam) for fam in families]
target = TargetDef(name='wti_3d_return_sign', price_path=DEFAULT_WTI_PATHS[0],
                   horizon_days=3, metric='return_sign', forbidden_uses=())
prices, _ = load_target_prices(target)
obs = build_target_observations(fevents, prices, horizon_days=3)
obs_post = [o for o in obs if o.decision_ts >= POST_2020_START]
kept_ts = kept_decision_ts([o.decision_ts for o in obs_post], purge_days=3, embargo_days=3)
kept_set = set(kept_ts)
print('post-thinning n:', sum(1 for o in obs_post if o.decision_ts in kept_set))
"
```

Output (deterministic given pit.duckdb at git commit
`748fdb07a19691132ea13b2ce93885cde8230610` or later):
`post-thinning n: 365`.

## Conclusion

The 3d horizon variant satisfies the spec §11 dependence requirement
**for directional and signed-return targets only**. The magnitude
target carries severe volatility-clustering autocorrelation that
collapses HAC effective N to 133, below the Phase 3 floor.
Recommendation: admit `WTI_FRONT_3D_RETURN_SIGN` and
`WTI_FRONT_3D_LOG_RETURN` to the target registry; defer
`WTI_FRONT_3D_RETURN_MAGNITUDE` until Phase 3 residual-based HAC can
demonstrate that a candidate model effectively absorbs the
volatility clustering.
