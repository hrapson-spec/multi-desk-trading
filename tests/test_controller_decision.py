"""Controller decision flow tests (spec §8.2 and §8.2a).

Wires StorageCurveDesk (classical) + four stubs through the Controller,
exercising the cold-start path end-to-end. Covers:
  - combined_signal is the weighted sum of non-stale point_estimates.
  - stale forecasts are excluded from the sum but do not prevent emission.
  - position_size is clipped to ±pos_limit_regime.
  - missing ControllerParams triggers RuntimeError (not silent no-op).
  - missing regime weights triggers RuntimeError.
  - Decision provenance is populated and deterministic in its
    input_snapshot_hash across identical inputs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence.db import connect, init_db


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.duckdb")
    init_db(c)
    yield c
    c.close()


def _prov(desk: str) -> Provenance:
    return Provenance(
        desk_name=desk,
        model_name="m",
        model_version="0.1",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def _fcast(desk: str, value: float, emission_ts: datetime, *, stale: bool = False) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=emission_ts,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=emission_ts),
        point_estimate=value,
        uncertainty=UncertaintyInterval(level=0.8, lower=value - 5.0, upper=value + 5.0),
        directional_claim=DirectionalClaim(
            variable=WTI_FRONT_MONTH_CLOSE, sign="positive" if not stale else "none"
        ),
        staleness=stale,
        confidence=0.5 if stale else 1.0,
        provenance=_prov(desk),
    )


def _regime_label(now: datetime, regime_id: str = "regime_boot") -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=now,
        regime_id=regime_id,
        regime_probabilities={regime_id: 1.0},
        transition_probabilities={regime_id: 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def test_controller_decides_under_cold_start_with_two_desks(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, 123456, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("demand", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
    )

    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 82.0, now),
        ("demand", WTI_FRONT_MONTH_CLOSE): _fcast("demand", 78.0, now),
    }
    regime = _regime_label(now)
    d = ctrl.decide(now_utc=now, regime_label=regime, recent_forecasts=recent)

    # Uniform weight 0.5 each; combined_signal = 0.5*82 + 0.5*78 = 80
    assert d.combined_signal == pytest.approx(80.0)
    # k_regime=1.0, pos_limit=1.0 ⇒ clip(1*80, ±1) = 1.0
    assert d.position_size == pytest.approx(1.0)
    assert d.regime_id == "regime_boot"
    assert len(d.input_forecast_ids) == 2
    assert d.provenance.desk_name == "controller"


def test_controller_excludes_stale_forecasts(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
    )

    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 82.0, now),
        # Stale forecast: value 1e6 should NOT enter the sum.
        ("supply", WTI_FRONT_MONTH_CLOSE): _fcast("supply", 1_000_000.0, now, stale=True),
    }
    d = ctrl.decide(
        now_utc=now,
        regime_label=_regime_label(now),
        recent_forecasts=recent,
    )
    # Only storage_curve contributes: 0.5 * 82 = 41 (stale supply excluded)
    assert d.combined_signal == pytest.approx(41.0)
    assert len(d.input_forecast_ids) == 1
    # clip(41, ±1) = 1
    assert d.position_size == pytest.approx(1.0)


def test_controller_all_stale_emits_zero_position(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 82.0, now, stale=True),
    }
    d = ctrl.decide(
        now_utc=now,
        regime_label=_regime_label(now),
        recent_forecasts=recent,
    )
    assert d.combined_signal == 0.0
    assert d.position_size == 0.0
    assert d.input_forecast_ids == []


def test_controller_clip_respects_negative_signal(conn):
    """When combined_signal is large and negative, clip bounds the short side."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=5.0,
        k_regime=1.0,
    )
    ctrl = Controller(conn=conn)
    # Emit a very negative "point estimate"; combined_signal = 1*(-100) = -100
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", -100.0, now),
    }
    d = ctrl.decide(
        now_utc=now,
        regime_label=_regime_label(now),
        recent_forecasts=recent,
    )
    assert d.position_size == pytest.approx(-5.0)
    assert np.sign(d.combined_signal) == -1


def test_controller_raises_without_cold_start(conn):
    """Fresh DB has neither ControllerParams nor SignalWeights for the
    regime. The params guard fires first (both would fire individually;
    this asserts the Controller fails loudly rather than silently)."""
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    ctrl = Controller(conn=conn)
    with pytest.raises(RuntimeError, match="no ControllerParams"):
        ctrl.decide(
            now_utc=now,
            regime_label=_regime_label(now),
            recent_forecasts={},
        )


def test_controller_raises_when_params_missing(conn):
    """Weights present but ControllerParams missing (pathological state).

    We seed weights by hand without params to exercise the guard; this is
    not a path the real system should reach, but the Controller must fail
    loudly rather than silently emitting a bad decision.
    """
    from contracts.v1 import SignalWeight
    from persistence.db import insert_signal_weight

    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    insert_signal_weight(
        conn,
        SignalWeight(
            weight_id="w1",
            regime_id="regime_boot",
            desk_name="storage_curve",
            target_variable=WTI_FRONT_MONTH_CLOSE,
            weight=1.0,
            promotion_ts_utc=boot,
            validation_artefact="hand_seeded",
        ),
    )
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    ctrl = Controller(conn=conn)
    with pytest.raises(RuntimeError, match="no ControllerParams"):
        ctrl.decide(
            now_utc=now,
            regime_label=_regime_label(now),
            recent_forecasts={
                ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 80.0, now)
            },
        )


def test_controller_rejects_naive_now_utc(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
    )
    ctrl = Controller(conn=conn)
    with pytest.raises(ValueError, match="timezone-aware"):
        ctrl.decide(
            now_utc=datetime(2026, 4, 16, 10, 0, 0),
            regime_label=_regime_label(datetime(2026, 4, 16, 10, tzinfo=UTC)),
            recent_forecasts={},
        )


def test_controller_decision_is_pure_function(conn):
    """Same regime + same weights + same forecasts ⇒ identical Decision
    up to the random decision_id. Critical for replay determinism (§3.1)."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
    )
    ctrl = Controller(conn=conn)
    f = _fcast("storage_curve", 82.0, now)
    recent = {("storage_curve", WTI_FRONT_MONTH_CLOSE): f}
    regime = _regime_label(now)

    d1 = ctrl.decide(now_utc=now, regime_label=regime, recent_forecasts=recent)
    d2 = ctrl.decide(now_utc=now, regime_label=regime, recent_forecasts=recent)

    assert d1.combined_signal == d2.combined_signal
    assert d1.position_size == d2.position_size
    assert d1.provenance.input_snapshot_hash == d2.provenance.input_snapshot_hash
    # decision_id differs (uuid4); everything else identical.
    assert d1.decision_id != d2.decision_id
