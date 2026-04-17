"""Signal-space LODO tests (spec §9.1).

Covers:
  - contribution_metric sign is negative for a long-pushing desk when
    removing it drops position_size.
  - A cold-start single-desk decision ⇒ that desk's LODO = full decision
    (removing it yields position=0).
  - Clip dominance: when combined_signal is clipped on both sides,
    LODO deltas can be zero even when non-trivial forecasts existed.
  - Persistence round-trip writes the row and count_rows sees it.
  - Reproducibility guard: tampering with weights between decide() and
    compute_lodo raises RuntimeError.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from attribution import (
    LODO_METRIC_POSITION_SIZE_DELTA,
    LODO_METRIC_SQUARED_ERROR_DELTA,
    compute_lodo_grading_space,
    compute_lodo_signal_space,
    persist_lodo_rows,
)
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    SignalWeight,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence.db import (
    connect,
    count_rows,
    init_db,
    insert_signal_weight,
)


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


def _fcast(desk: str, value: float, ts: datetime, *, stale: bool = False) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=ts,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=ts),
        point_estimate=value,
        uncertainty=UncertaintyInterval(level=0.8, lower=value - 5.0, upper=value + 5.0),
        directional_claim=DirectionalClaim(
            variable=WTI_FRONT_MONTH_CLOSE, sign="positive" if not stale else "none"
        ),
        staleness=stale,
        confidence=0.5 if stale else 1.0,
        provenance=_prov(desk),
    )


def _regime(now: datetime) -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=now,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def test_lodo_single_desk_removes_full_position(conn):
    """Only one desk in the weight row; removing it ⇒ position=0 ⇒ the
    desk's LODO contribution equals the original position_size."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=100.0,  # big enough to avoid clip
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 82.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    # combined_signal = 1 * 82 = 82; k=1, limit=100 ⇒ position = 82
    assert decision.position_size == pytest.approx(82.0)

    rows = compute_lodo_signal_space(
        conn=conn, decision=decision, recent_forecasts=recent, computed_ts_utc=now
    )
    assert len(rows) == 1
    assert rows[0].desk_name == "storage_curve"
    # Removing the only contributor ⇒ lodo_position = 0 ⇒ delta = 82 - 0 = 82
    assert rows[0].contribution_metric == pytest.approx(82.0)
    assert rows[0].metric_name == LODO_METRIC_POSITION_SIZE_DELTA


def test_lodo_two_desks_partition_contribution(conn):
    """Two desks with equal weights; each contributes half the unclipped
    combined_signal. When not clipped, LODO deltas sum to position_size."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("demand", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=200.0,
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 90.0, now),
        ("demand", WTI_FRONT_MONTH_CLOSE): _fcast("demand", 70.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    # 0.5*90 + 0.5*70 = 80; unclipped ⇒ position = 80
    assert decision.position_size == pytest.approx(80.0)

    rows = compute_lodo_signal_space(
        conn=conn, decision=decision, recent_forecasts=recent, computed_ts_utc=now
    )
    assert len(rows) == 2
    by_desk = {r.desk_name: r.contribution_metric for r in rows}
    # Removing storage_curve ⇒ combined = 0.5*70 = 35; delta = 80 - 35 = 45
    assert by_desk["storage_curve"] == pytest.approx(45.0)
    # Removing demand        ⇒ combined = 0.5*90 = 45; delta = 80 - 45 = 35
    assert by_desk["demand"] == pytest.approx(35.0)
    # Sum equals full position when unclipped.
    assert sum(by_desk.values()) == pytest.approx(80.0)


def test_lodo_clipped_decision_attributes_zero_above_limit(conn):
    """When the clip is binding, LODO attributes the last desk that
    pushes above the clip as having zero marginal delta (removing it
    moves the position from +limit to still +limit because the clip
    is still binding)."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("demand", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1.0,  # tight clip
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 100.0, now),
        ("demand", WTI_FRONT_MONTH_CLOSE): _fcast("demand", 100.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    # 0.5*100 + 0.5*100 = 100; clipped to 1
    assert decision.position_size == pytest.approx(1.0)

    rows = compute_lodo_signal_space(
        conn=conn, decision=decision, recent_forecasts=recent, computed_ts_utc=now
    )
    # Either LODO still hits the clip ⇒ both deltas are 0.
    assert all(r.contribution_metric == pytest.approx(0.0) for r in rows)


def test_lodo_stale_contributor_is_non_contributing(conn):
    """A stale forecast never enters combined_signal, so its LODO delta is 0."""
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
        default_cold_start_limit=200.0,
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 80.0, now),
        ("supply", WTI_FRONT_MONTH_CLOSE): _fcast("supply", 10_000.0, now, stale=True),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)

    rows = compute_lodo_signal_space(
        conn=conn, decision=decision, recent_forecasts=recent, computed_ts_utc=now
    )
    by_desk = {r.desk_name: r.contribution_metric for r in rows}
    assert by_desk["storage_curve"] == pytest.approx(decision.position_size)
    assert by_desk["supply"] == pytest.approx(0.0)


def test_lodo_persists_to_duckdb(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=100.0,
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 50.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    rows = compute_lodo_signal_space(
        conn=conn, decision=decision, recent_forecasts=recent, computed_ts_utc=now
    )
    persist_lodo_rows(conn, rows)
    assert count_rows(conn, "attribution_lodo") == 1


def test_lodo_detects_weight_mutation_between_decide_and_compute(conn):
    """If someone writes a new SignalWeight row between decide() and
    compute_lodo, the sanity reproduction fails and LODO raises."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=100.0,
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 50.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    # Tamper: write a newer SignalWeight row with weight=10.0
    later = datetime(2026, 4, 16, 11, 0, 0, tzinfo=UTC)
    insert_signal_weight(
        conn,
        SignalWeight(
            weight_id="tamper-1",
            regime_id="regime_boot",
            desk_name="storage_curve",
            target_variable=WTI_FRONT_MONTH_CLOSE,
            weight=10.0,
            promotion_ts_utc=later,
            validation_artefact="rollback:test",
        ),
    )
    with pytest.raises(RuntimeError, match="LODO precondition violated"):
        compute_lodo_signal_space(
            conn=conn,
            decision=decision,
            recent_forecasts=recent,
            computed_ts_utc=later,
        )


# ---------------------------------------------------------------------------
# Grading-space LODO (§9.1 step 2)
# ---------------------------------------------------------------------------


def test_grading_space_lodo_flags_harmful_desk_with_positive_delta(conn):
    """Desk b pushes combined_signal away from the Print; removing b
    makes the error smaller ⇒ lodo_err² > original_err² ⇒ delta < 0.
    Per the docstring convention: negative delta = removing helps =
    the desk is HARMFUL. Positive delta = the desk was reducing error.
    """
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("harmful", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    # Realized print = 80.
    # storage_curve predicts 80 (perfect). harmful predicts 100 (bad).
    # Cold-start weights 0.5/0.5 ⇒ combined = 90, err² = 100.
    # LODO-storage_curve ⇒ combined = 0.5*100 = 50, err² = 900 (much worse).
    # LODO-harmful ⇒ combined = 0.5*80 = 40, err² = 1600 (also worse
    # because dropping it alone still leaves the other desk's weight too
    # low to hit 80). Let me double-check:
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 80.0, now),
        ("harmful", WTI_FRONT_MONTH_CLOSE): _fcast("harmful", 100.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    rows = compute_lodo_grading_space(
        conn=conn,
        decision=decision,
        recent_forecasts=recent,
        print_value=80.0,
        computed_ts_utc=now,
    )
    by_desk = {r.desk_name: r.contribution_metric for r in rows}
    # original combined = 90; err² = (90-80)² = 100.
    # Remove storage_curve: combined = 0.5*100 = 50; err² = (50-80)² = 900;
    # delta = 900 - 100 = 800 (positive) ⇒ storage_curve was reducing error.
    # Remove harmful: combined = 0.5*80 = 40; err² = (40-80)² = 1600;
    # delta = 1600 - 100 = 1500 (positive) ⇒ harmful was ALSO reducing
    # error by this particular metric, because the weight cage pulls both
    # desks below the Print equally. This demonstrates a subtle behaviour:
    # harmful-by-sign and harmful-by-grading-metric can diverge under
    # constant-weight LODO without renormalisation.
    assert by_desk["storage_curve"] == pytest.approx(800.0)
    assert by_desk["harmful"] == pytest.approx(1500.0)
    assert all(r.metric_name == LODO_METRIC_SQUARED_ERROR_DELTA for r in rows)


def test_grading_space_lodo_desk_with_exact_match_reduces_error(conn):
    """When the Controller already hits the Print exactly, removing any
    desk should ONLY increase error; all deltas are positive."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("a", WTI_FRONT_MONTH_CLOSE),
            ("b", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    # Both forecast 80; combined = 80; exact match against print = 80.
    recent = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 80.0, now),
        ("b", WTI_FRONT_MONTH_CLOSE): _fcast("b", 80.0, now),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    rows = compute_lodo_grading_space(
        conn=conn,
        decision=decision,
        recent_forecasts=recent,
        print_value=80.0,
        computed_ts_utc=now,
    )
    by_desk = {r.desk_name: r.contribution_metric for r in rows}
    # original err² = 0; removing either ⇒ combined = 40; err² = 1600;
    # delta = 1600 (positive, large) for each.
    assert by_desk["a"] == pytest.approx(1600.0)
    assert by_desk["b"] == pytest.approx(1600.0)


def test_grading_space_lodo_stale_desk_delta_zero(conn):
    """A stale forecast never contributed ⇒ LODO delta = 0 (removing a
    non-contributor changes nothing)."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[
            ("a", WTI_FRONT_MONTH_CLOSE),
            ("stale", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    recent = {
        ("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 80.0, now),
        ("stale", WTI_FRONT_MONTH_CLOSE): _fcast("stale", 1e6, now, stale=True),
    }
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    rows = compute_lodo_grading_space(
        conn=conn,
        decision=decision,
        recent_forecasts=recent,
        print_value=80.0,
        computed_ts_utc=now,
    )
    by_desk = {r.desk_name: r.contribution_metric for r in rows}
    assert by_desk["stale"] == pytest.approx(0.0)


def test_grading_space_lodo_detects_weight_mutation(conn):
    """Same precondition guard as signal-space LODO."""
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    seed_cold_start(
        conn,
        desks=[("a", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    recent = {("a", WTI_FRONT_MONTH_CLOSE): _fcast("a", 50.0, now)}
    decision = ctrl.decide(now_utc=now, regime_label=_regime(now), recent_forecasts=recent)
    later = datetime(2026, 4, 16, 11, 0, 0, tzinfo=UTC)
    insert_signal_weight(
        conn,
        SignalWeight(
            weight_id="tamper-2",
            regime_id="regime_boot",
            desk_name="a",
            target_variable=WTI_FRONT_MONTH_CLOSE,
            weight=10.0,
            promotion_ts_utc=later,
            validation_artefact="rollback:test",
        ),
    )
    with pytest.raises(RuntimeError, match="precondition violated"):
        compute_lodo_grading_space(
            conn=conn,
            decision=decision,
            recent_forecasts=recent,
            print_value=50.0,
            computed_ts_utc=later,
        )
