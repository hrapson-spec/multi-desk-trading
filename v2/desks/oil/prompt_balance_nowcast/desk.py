"""prompt_balance_nowcast — v2.0 first desk.

This module ships a **scaffold** implementation: a shell that reads the
correct PIT-safe feature view and emits a valid ForecastV2 under the
real v2 contract, but whose quantile output is a fixed-variance
zero-mean Gaussian (the Layer-3 baseline B0, EWMA-vol reference).

Replacing this with the genuine dynamic-factor nowcast is the payload
of the S1→S2 promotion. The prereg for that promotion specifies:
    model_class: dynamic_factor_nowcast_v1
    hyperparameters: {...}
    training_window: (decided by Layer-1 PIT audit)

This file deliberately avoids inventing the real model. Having a
scaffold that satisfies the contract end-to-end lets B5 build the
evaluation stack without the model having to land first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import prod

from scipy.stats import norm

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.forecast_v2 import ForecastV2
from v2.desks.base import ConcreteDeskV2
from v2.feature_view.spec import FeatureSpec
from v2.feature_view.view import FeatureView

# Default 5-day log-return dispersion used by the scaffold. This is a
# placeholder that matches the order of magnitude of realised WTI
# 5-day log-return vol; the real desk will replace this with a
# predictive sigma derived from the nowcast state.
_SCAFFOLD_SIGMA_5D = 0.04

# Default 1-business-day TTL on each forecast (decision contract §4).
# The scaffold and the real desk share this default; tightening the
# TTL is a prereg choice.
_SCAFFOLD_TTL = timedelta(days=1)


class PromptBalanceNowcastDesk(ConcreteDeskV2):
    family_id = "oil_wti_5d"
    desk_id = "prompt_balance_nowcast"
    distribution_version = "0.0.1-scaffold"

    def feature_specs(self) -> list[FeatureSpec]:
        """Declared input set for this desk.

        When the real model lands, this list is frozen by the prereg
        and any addition/removal is a typed contract deviation.
        """
        return [
            FeatureSpec(name="eia_crude_stocks", source="eia_wpsr", series="crude_stocks"),
            FeatureSpec(name="eia_gasoline_stocks", source="eia_wpsr", series="gasoline_stocks"),
            FeatureSpec(
                name="eia_distillate_stocks", source="eia_wpsr", series="distillate_stocks"
            ),
            FeatureSpec(name="refinery_runs", source="eia_wpsr", series="refinery_runs"),
            FeatureSpec(name="crude_imports", source="eia_wpsr", series="crude_imports"),
            FeatureSpec(name="crude_exports", source="eia_wpsr", series="crude_exports"),
            FeatureSpec(
                name="wti_calendar_spread_1_2",
                source="wti_front_month",
                series="spread_1_2",
                required=False,
            ),
        ]

    def forecast(
        self,
        view: FeatureView,
        *,
        prereg_hash: str,
        code_commit: str,
    ) -> ForecastV2:
        decision_ts = _ensure_utc(view.as_of_ts)
        valid_until = decision_ts + _SCAFFOLD_TTL

        # Abstention: any required feature missing → abstain with a
        # reason. The synthesiser will cascade this via the any-hard-gate
        # family rule.
        if view.any_required_missing:
            missing = [name for name, m in view.missingness.items() if m]
            return self._abstain(
                view,
                decision_ts=decision_ts,
                valid_until=valid_until,
                prereg_hash=prereg_hash,
                code_commit=code_commit,
                reason=f"required feature(s) missing: {sorted(missing)}",
            )

        # Scaffold: zero-mean Gaussian with a fixed σ — the B0 baseline.
        mu = 0.0
        sigma = _SCAFFOLD_SIGMA_5D
        quantile_vector = tuple(mu + sigma * norm.ppf(q) for q in FIXED_QUANTILE_LEVELS)

        # Quality propagation: product of per-source quality multipliers
        # clipped to [0, 1]. Used as ForecastV2.data_quality_score.
        if view.source_eligibility:
            dq = prod(e.quality_multiplier for e in view.source_eligibility.values())
        else:
            dq = 1.0
        dq = max(0.0, min(1.0, dq))

        # The scaffold cannot calibrate — calibration_score = 0.5 is a
        # neutral prior until the real desk tracks rolling pinball loss
        # vs baselines.
        calibration_score = 0.5

        return ForecastV2(
            family_id=self.family_id,
            desk_id=self.desk_id,
            decision_ts=decision_ts,
            distribution_version=self.distribution_version,
            target_variable="WTI_FRONT_1W_LOG_RETURN",
            target_horizon="5d",
            decision_unit=DecisionUnit.LOG_RETURN,
            quantile_levels=FIXED_QUANTILE_LEVELS,
            quantile_vector=quantile_vector,
            calibration_score=calibration_score,
            data_quality_score=dq,
            valid_until_ts=valid_until,
            abstain=False,
            abstain_reason=None,
            feature_view_hash=view.view_hash,
            prereg_hash=prereg_hash,
            code_commit=code_commit,
            source_eligibility=view.source_eligibility,
        )

    def _abstain(
        self,
        view: FeatureView,
        *,
        decision_ts: datetime,
        valid_until: datetime,
        prereg_hash: str,
        code_commit: str,
        reason: str,
    ) -> ForecastV2:
        return ForecastV2(
            family_id=self.family_id,
            desk_id=self.desk_id,
            decision_ts=decision_ts,
            distribution_version=self.distribution_version,
            target_variable="WTI_FRONT_1W_LOG_RETURN",
            target_horizon="5d",
            decision_unit=DecisionUnit.LOG_RETURN,
            quantile_levels=FIXED_QUANTILE_LEVELS,
            # An abstained forecast still carries a valid-length vector;
            # monotonicity is not required. Use zeros so downstream code
            # never panics on NaN arithmetic if it forgets to check abstain.
            quantile_vector=tuple(0.0 for _ in FIXED_QUANTILE_LEVELS),
            calibration_score=0.0,
            data_quality_score=0.0,
            valid_until_ts=valid_until,
            abstain=True,
            abstain_reason=reason,
            feature_view_hash=view.view_hash,
            prereg_hash=prereg_hash,
            code_commit=code_commit,
            source_eligibility=view.source_eligibility,
        )


def _ensure_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)
