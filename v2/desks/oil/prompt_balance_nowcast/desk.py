"""prompt_balance_nowcast — v2.0 first desk.

Scaffold implementation: a shell that reads the correct PIT-safe feature
view and emits a valid ForecastV2 under contract v2.0.1. The quantile
output is a fixed-variance zero-mean Gaussian (the Layer-3 baseline B0,
EWMA-vol reference). Replacement by the genuine dynamic-factor nowcast
is the S1→S2 promotion payload.

See spec.md for the Layer-2 mechanism memo and pre-registered claims.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from math import prod

from scipy.stats import norm

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.forecast_v2 import CalibrationMetadata, ForecastV2
from v2.desks.base import ConcreteDeskV2
from v2.feature_view.spec import FeatureSpec
from v2.feature_view.view import FeatureView

_SCAFFOLD_SIGMA_5D = 0.04
_SCAFFOLD_TTL = timedelta(days=1)
_SCAFFOLD_CALIBRATION = CalibrationMetadata(
    method="rolling_pinball_ratio",
    baseline_id="B0_ewma_gaussian",
    rolling_window_n=0,
    sample_count=0,
    segment=None,
)


class PromptBalanceNowcastDesk(ConcreteDeskV2):
    family_id = "oil_wti_5d"
    desk_id = "prompt_balance_nowcast"
    distribution_version = "0.0.1-scaffold"

    def feature_specs(self) -> list[FeatureSpec]:
        return [
            FeatureSpec(
                name="eia_crude_stocks", source="eia", dataset="wpsr", series="crude_stocks"
            ),
            FeatureSpec(
                name="eia_gasoline_stocks",
                source="eia",
                dataset="wpsr",
                series="gasoline_stocks",
            ),
            FeatureSpec(
                name="eia_distillate_stocks",
                source="eia",
                dataset="wpsr",
                series="distillate_stocks",
            ),
            FeatureSpec(name="refinery_runs", source="eia", dataset="wpsr", series="refinery_runs"),
            FeatureSpec(name="crude_imports", source="eia", dataset="wpsr", series="crude_imports"),
            FeatureSpec(name="crude_exports", source="eia", dataset="wpsr", series="crude_exports"),
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
        contract_hash: str = "",
        release_calendar_version: str = "",
        emitted_ts: datetime | None = None,
    ) -> ForecastV2:
        decision_ts = view.as_of_ts
        emitted = emitted_ts if emitted_ts is not None else datetime.now(UTC)
        if emitted < decision_ts:
            # The emitter should never time-travel: if a caller passed a
            # stale ts, clamp forward. The validator still enforces
            # emitted_ts >= decision_ts on the final object.
            emitted = decision_ts
        valid_until = decision_ts + _SCAFFOLD_TTL

        if view.any_required_missing:
            missing = sorted(name for name, m in view.missingness.items() if m)
            return ForecastV2.build_from_view(
                view=view,
                family_id=self.family_id,
                desk_id=self.desk_id,
                distribution_version=self.distribution_version,
                target_variable="WTI_FRONT_1W_LOG_RETURN",
                target_horizon="5d",
                decision_unit=DecisionUnit.LOG_RETURN,
                quantile_vector=tuple(0.0 for _ in FIXED_QUANTILE_LEVELS),
                calibration_score=0.0,
                calibration_metadata=_SCAFFOLD_CALIBRATION,
                data_quality_score=0.0,
                valid_until_ts=valid_until,
                emitted_ts=emitted,
                abstain=True,
                abstain_reason=f"required feature(s) missing: {missing}",
                prereg_hash=prereg_hash,
                code_commit=code_commit,
                contract_hash=contract_hash,
                release_calendar_version=release_calendar_version,
            )

        # Scaffold: zero-mean Gaussian with a fixed σ — the B0 baseline.
        mu = 0.0
        sigma = _SCAFFOLD_SIGMA_5D
        quantile_vector = tuple(mu + sigma * norm.ppf(q) for q in FIXED_QUANTILE_LEVELS)

        if view.source_eligibility:
            dq = prod(e.quality_multiplier for e in view.source_eligibility.values())
        else:
            dq = 1.0
        dq = max(0.0, min(1.0, dq))

        return ForecastV2.build_from_view(
            view=view,
            family_id=self.family_id,
            desk_id=self.desk_id,
            distribution_version=self.distribution_version,
            target_variable="WTI_FRONT_1W_LOG_RETURN",
            target_horizon="5d",
            decision_unit=DecisionUnit.LOG_RETURN,
            quantile_vector=quantile_vector,
            calibration_score=0.5,
            calibration_metadata=_SCAFFOLD_CALIBRATION,
            data_quality_score=dq,
            valid_until_ts=valid_until,
            emitted_ts=emitted,
            abstain=False,
            abstain_reason=None,
            prereg_hash=prereg_hash,
            code_commit=code_commit,
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
        )
