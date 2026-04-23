"""v2 evaluation stack (ROWF-CPCV v2.0).

Layer-3 promotion evidence:
    outcomes.RealisedOutcome        pair a forecast with its realised Y_t
    scoring.pinball_loss            per-quantile-level pinball losses
    scoring.mean_pinball_loss       scalar loss (primary Layer-3 metric)
    scoring.approx_crps             quantile-based CRPS proxy
    scoring.interval_coverage       empirical coverage vs nominal
    scoring.diebold_mariano_hac     paired forecast comparison under HAC variance
    scoring.moving_block_bootstrap  CI on mean loss differentials
    baselines.B0EWMAGaussian        zero-mean Gaussian, EWMA-vol
    baselines.B1Empirical           empirical distribution with time decay
    shadow_rule.monotone_b_tilde    pre-registered decision translation
    cost_model                      two-scenario fee + slippage stress

Walk-forward and CPCV drivers land as B5b.
"""

from v2.eval.baselines import B0EWMAGaussian, B1Empirical
from v2.eval.cost_model import CostParams, CostScenario, apply_costs
from v2.eval.cpcv import (
    CPCVParams,
    CPCVSplit,
    assert_no_label_leakage,
    chronological_block_bounds,
    generate_cpcv_splits,
)
from v2.eval.outcomes import RealisedOutcome
from v2.eval.scoring import (
    approx_crps_from_quantiles,
    diebold_mariano_hac,
    interval_coverage,
    mean_pinball_loss,
    moving_block_bootstrap,
    pinball_loss,
)
from v2.eval.shadow_rule import monotone_b_tilde
from v2.eval.walk_forward import (
    DailyForecaster,
    WalkForwardParams,
    WalkForwardResult,
    run_walk_forward,
)

__all__ = [
    "B0EWMAGaussian",
    "B1Empirical",
    "CPCVParams",
    "CPCVSplit",
    "CostParams",
    "CostScenario",
    "DailyForecaster",
    "RealisedOutcome",
    "WalkForwardParams",
    "WalkForwardResult",
    "apply_costs",
    "approx_crps_from_quantiles",
    "assert_no_label_leakage",
    "chronological_block_bounds",
    "diebold_mariano_hac",
    "generate_cpcv_splits",
    "interval_coverage",
    "mean_pinball_loss",
    "monotone_b_tilde",
    "moving_block_bootstrap",
    "pinball_loss",
    "run_walk_forward",
]
