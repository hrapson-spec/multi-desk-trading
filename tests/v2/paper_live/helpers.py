"""Test helpers for B6b paper-live tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS, DecisionUnit
from v2.contracts.forecast_v2 import CalibrationMetadata, ForecastV2
from v2.feature_view.view import FeatureView

CONTRACT_HASH = "sha256:contract"
PREREG_HASH = "sha256:prereg"
CODE_COMMIT = "abcdef0"
RELEASE_CALENDAR_VERSION = "eia_wpsr:1.0.0"
FAMILY = "oil_wti_5d"

_CALIBRATION = CalibrationMetadata(
    method="test",
    baseline_id="B0",
    rolling_window_n=0,
    sample_count=0,
)


def make_view(
    decision_ts: datetime,
    *,
    family: str = FAMILY,
    desk_id: str = "desk_a",
) -> FeatureView:
    return FeatureView(
        as_of_ts=decision_ts,
        family=family,
        desk=desk_id,
        specs=(),
        features={},
        source_eligibility={},
        missingness={},
        stale_flags={},
        manifest_ids={},
        forward_fill_used={},
        view_hash=f"vh:{family}:{desk_id}:{decision_ts.isoformat()}",
    )


def make_forecast(
    decision_ts: datetime,
    *,
    desk_id: str = "desk_a",
    emitted_ts: datetime | None = None,
    valid_until_ts: datetime | None = None,
    quantile_vector: tuple[float, ...] = (
        -0.08,
        -0.04,
        -0.01,
        0.008,
        0.02,
        0.05,
        0.09,
    ),
    calibration_score: float = 1.0,
    data_quality_score: float = 1.0,
    abstain: bool = False,
    abstain_reason: str | None = None,
) -> ForecastV2:
    if emitted_ts is None:
        emitted_ts = decision_ts
    if valid_until_ts is None:
        valid_until_ts = decision_ts + timedelta(days=1)
    qv = tuple(0.0 for _ in FIXED_QUANTILE_LEVELS) if abstain else quantile_vector
    return ForecastV2.build_from_view(
        view=make_view(decision_ts, desk_id=desk_id),
        family_id=FAMILY,
        desk_id=desk_id,
        distribution_version="test",
        target_variable="WTI_FRONT_1W_LOG_RETURN",
        target_horizon="5d",
        decision_unit=DecisionUnit.LOG_RETURN,
        quantile_vector=qv,
        calibration_score=calibration_score,
        calibration_metadata=_CALIBRATION,
        data_quality_score=data_quality_score,
        valid_until_ts=valid_until_ts,
        emitted_ts=emitted_ts,
        prereg_hash=PREREG_HASH,
        code_commit=CODE_COMMIT,
        contract_hash=CONTRACT_HASH,
        release_calendar_version=RELEASE_CALENDAR_VERSION,
        abstain=abstain,
        abstain_reason=abstain_reason,
    )


def dt(hour: int = 21) -> datetime:
    return datetime(2026, 4, 22, hour, 0, tzinfo=UTC)
