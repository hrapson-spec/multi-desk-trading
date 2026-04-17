"""Persistence round-trip and replay-query tests."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import ControllerParams, Decision, Provenance, SignalWeight
from persistence import (
    count_rows,
    get_latest_controller_params,
    get_latest_signal_weights,
    insert_controller_params,
    insert_decision,
    insert_forecast,
    insert_print,
    insert_signal_weight,
    replay_forecasts,
)


def _prov(**kw):
    return Provenance(
        desk_name=kw.get("desk_name", "d"),
        model_name="m",
        model_version="1.0.0",
        input_snapshot_hash="a" * 64,
        spec_hash="b" * 64,
        code_commit="c" * 40,
    )


def test_init_and_count(tmp_db):
    # All 11 tables exist and are empty.
    for table in [
        "forecasts",
        "prints",
        "grades",
        "decisions",
        "signal_weights",
        "controller_params",
        "attribution_lodo",
        "attribution_shapley",
        "research_loop_events",
        "model_registry",
        "regime_labels",
    ]:
        assert count_rows(tmp_db, table) == 0


def test_forecast_print_roundtrip(tmp_db, stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory()
    p = stub_print_factory()
    insert_forecast(tmp_db, f)
    insert_print(tmp_db, p)
    assert count_rows(tmp_db, "forecasts") == 1
    assert count_rows(tmp_db, "prints") == 1

    rows = list(
        replay_forecasts(
            tmp_db,
            f.emission_ts_utc - timedelta(hours=1),
            f.emission_ts_utc + timedelta(hours=1),
        )
    )
    assert len(rows) == 1
    assert rows[0]["forecast_id"] == f.forecast_id


def test_signal_weight_tie_break(tmp_db):
    """When two rows share promotion_ts_utc, the query picks lexicographically
    greatest weight_id (spec §8.3)."""
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    w_a = SignalWeight(
        weight_id="zzz_a",
        regime_id="r1",
        desk_name="d1",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        weight=0.1,
        promotion_ts_utc=ts,
        validation_artefact="first",
    )
    w_b = SignalWeight(
        weight_id="zzz_b",
        regime_id="r1",
        desk_name="d1",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        weight=0.2,
        promotion_ts_utc=ts,
        validation_artefact="second",
    )
    insert_signal_weight(tmp_db, w_a)
    insert_signal_weight(tmp_db, w_b)
    latest = get_latest_signal_weights(tmp_db, "r1")
    assert len(latest) == 1
    assert latest[0]["weight_id"] == "zzz_b"


def test_controller_params_latest(tmp_db):
    ts1 = datetime(2026, 1, 1, tzinfo=UTC)
    ts2 = ts1 + timedelta(days=1)
    cp1 = ControllerParams(
        params_id="p1",
        regime_id="r1",
        k_regime=1.0,
        pos_limit_regime=1.0,
        promotion_ts_utc=ts1,
        validation_artefact="cold_start",
    )
    cp2 = ControllerParams(
        params_id="p2",
        regime_id="r1",
        k_regime=2.0,
        pos_limit_regime=2.0,
        promotion_ts_utc=ts2,
        validation_artefact="promoted",
    )
    insert_controller_params(tmp_db, cp1)
    insert_controller_params(tmp_db, cp2)
    latest = get_latest_controller_params(tmp_db, "r1")
    assert latest is not None and latest["params_id"] == "p2"
    assert latest["k_regime"] == 2.0


def test_decision_insert(tmp_db):
    d = Decision(
        decision_id=str(uuid.uuid4()),
        emission_ts_utc=datetime(2026, 1, 7, tzinfo=UTC),
        regime_id="r1",
        combined_signal=0.5,
        position_size=10.0,
        input_forecast_ids=["f1", "f2"],
        provenance=_prov(desk_name="controller"),
    )
    insert_decision(tmp_db, d)
    assert count_rows(tmp_db, "decisions") == 1
