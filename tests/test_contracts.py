"""Unit tests for contracts/v1.py invariants."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    ClockHorizon,
    ControllerParams,
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Print,
    Provenance,
    UncertaintyInterval,
)


def test_provenance_is_frozen():
    p = Provenance(
        desk_name="d",
        model_name="m",
        model_version="1.0.0",
        input_snapshot_hash="a" * 64,
        spec_hash="b" * 64,
        code_commit="c" * 40,
    )
    with pytest.raises(ValidationError):
        p.desk_name = "other"  # type: ignore[misc]


def test_event_horizon_rejects_naive_datetime():
    with pytest.raises(ValidationError):
        EventHorizon(event_id="x", expected_ts_utc=datetime(2026, 1, 1))  # naive


def test_uncertainty_requires_lower_le_upper():
    with pytest.raises(ValidationError):
        UncertaintyInterval(level=0.8, lower=1.0, upper=0.5)


def test_forecast_rejects_unknown_target():
    with pytest.raises(ValidationError):
        Forecast(
            forecast_id="f1",
            emission_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
            target_variable="made_up_target",
            horizon=ClockHorizon(duration=timedelta(days=1)),
            point_estimate=0.0,
            uncertainty=UncertaintyInterval(level=0.8, lower=-1.0, upper=1.0),
            directional_claim=DirectionalClaim(variable="made_up_target", sign="positive"),
            provenance=Provenance(
                desk_name="d",
                model_name="m",
                model_version="1.0.0",
                input_snapshot_hash="a" * 64,
                spec_hash="b" * 64,
                code_commit="c" * 40,
            ),
        )


def test_forecast_rejects_naive_emission_ts():
    with pytest.raises(ValidationError):
        Forecast(
            forecast_id="f1",
            emission_ts_utc=datetime(2026, 1, 1),  # naive
            target_variable=WTI_FRONT_MONTH_CLOSE,
            horizon=ClockHorizon(duration=timedelta(days=1)),
            point_estimate=0.0,
            uncertainty=UncertaintyInterval(level=0.8, lower=-1.0, upper=1.0),
            directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
            provenance=Provenance(
                desk_name="d",
                model_name="m",
                model_version="1.0.0",
                input_snapshot_hash="a" * 64,
                spec_hash="b" * 64,
                code_commit="c" * 40,
            ),
        )


def test_print_rejects_unknown_target():
    with pytest.raises(ValidationError):
        Print(
            print_id="p1",
            realised_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
            target_variable="not_registered",
            value=0.0,
        )


def test_controller_params_rejects_negative_pos_limit():
    with pytest.raises(ValidationError):
        ControllerParams(
            params_id="cp1",
            regime_id="r1",
            k_regime=1.0,
            pos_limit_regime=-0.1,
            promotion_ts_utc=datetime(2026, 1, 1, tzinfo=UTC),
            validation_artefact="test",
        )


def test_research_loop_event_type_literal():
    # valid type passes; invalid raises
    from contracts.v1 import ResearchLoopEvent

    ResearchLoopEvent(
        event_id="e1",
        event_type="data_ingestion_failure",
        triggered_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        priority=1,
        payload={},
    )
    with pytest.raises(ValidationError):
        ResearchLoopEvent(
            event_id="e1",
            event_type="bogus_type",  # type: ignore[arg-type]
            triggered_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
            priority=1,
            payload={},
        )
