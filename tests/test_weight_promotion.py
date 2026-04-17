"""Weight-promotion tests (spec §8.3, research_loop.promotion).

Covers v0.2 behaviour:
  - Shapley-proportional weights normalise to 1 across desks.
  - A dominant desk's Shapley value dominates its new weight.
  - Zero-Shapley desks get weight 0.
  - Desks absent from the Shapley rollup retain current weight.
  - Promoted rows are read by Controller on next decide() via
    (promotion_ts_utc, weight_id) tie-break.
  - All-zero Shapley values preserve the current weights (no bogus
    renormalisation).
  - Naive new_promotion_ts_utc raises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    AttributionShapley,
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence.db import connect, get_latest_signal_weights, init_db
from research_loop import (
    PROMOTION_ARTEFACT_SHAPLEY_V02,
    propose_and_promote_from_shapley,
    propose_weights_from_shapley,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "promo.duckdb")
    init_db(c)
    yield c
    c.close()


def _shapley(desk: str, value: float, ts: datetime) -> AttributionShapley:
    return AttributionShapley(
        attribution_id=str(uuid.uuid4()),
        review_ts_utc=ts,
        desk_name=desk,
        shapley_value=value,
        metric_name="position_size_delta",
        n_decisions=5,
        coalitions_mode="exact",
    )


def _prov(desk: str) -> Provenance:
    return Provenance(
        desk_name=desk,
        model_name="m",
        model_version="0.1",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def _fcast(desk: str, value: float, ts: datetime) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=ts,
        target_variable=WTI_FRONT_MONTH_CLOSE,
        horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=ts),
        point_estimate=value,
        uncertainty=UncertaintyInterval(level=0.8, lower=value - 5.0, upper=value + 5.0),
        directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
        staleness=False,
        confidence=1.0,
        provenance=_prov(desk),
    )


def _regime(ts: datetime) -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=ts,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def _current_weights_stub(desks_with_w: list[tuple[str, float]]) -> list[dict]:
    return [
        {
            "desk_name": d,
            "target_variable": WTI_FRONT_MONTH_CLOSE,
            "weight": w,
            "regime_id": "regime_boot",
        }
        for d, w in desks_with_w
    ]


# ---------------------------------------------------------------------------
# Proposer unit tests
# ---------------------------------------------------------------------------


def test_propose_normalises_shapley_magnitudes():
    ts = datetime(2026, 4, 20, 16, 30, 0, tzinfo=UTC)
    current = _current_weights_stub([("a", 0.333), ("b", 0.333), ("c", 0.333)])
    shapley = [
        _shapley("a", 60.0, ts),
        _shapley("b", 15.0, ts),
        _shapley("c", 25.0, ts),
    ]
    proposal = propose_weights_from_shapley(
        shapley_rows=shapley,
        current_weights=current,
        new_promotion_ts_utc=ts,
    )
    by_desk = {p.desk_name: p.weight for p in proposal}
    assert by_desk["a"] == pytest.approx(0.6)
    assert by_desk["b"] == pytest.approx(0.15)
    assert by_desk["c"] == pytest.approx(0.25)
    assert sum(by_desk.values()) == pytest.approx(1.0)
    assert all(p.validation_artefact == PROMOTION_ARTEFACT_SHAPLEY_V02 for p in proposal)


def test_propose_handles_negative_shapley_as_absolute_magnitude():
    ts = datetime(2026, 4, 20, 16, 30, 0, tzinfo=UTC)
    current = _current_weights_stub([("a", 0.5), ("b", 0.5)])
    # Desk b pushes strongly negative — it still has |influence| so it
    # retains a proportional weight. The Controller's sizing sign comes
    # from desk_forecast.point_estimate, not from the weight's sign.
    shapley = [_shapley("a", 10.0, ts), _shapley("b", -30.0, ts)]
    proposal = propose_weights_from_shapley(
        shapley_rows=shapley,
        current_weights=current,
        new_promotion_ts_utc=ts,
    )
    by_desk = {p.desk_name: p.weight for p in proposal}
    assert by_desk["a"] == pytest.approx(0.25)
    assert by_desk["b"] == pytest.approx(0.75)


def test_propose_zero_shapley_desk_gets_zero_weight():
    ts = datetime(2026, 4, 20, 16, 30, 0, tzinfo=UTC)
    current = _current_weights_stub([("a", 0.5), ("b", 0.5)])
    shapley = [_shapley("a", 100.0, ts), _shapley("b", 0.0, ts)]
    proposal = propose_weights_from_shapley(
        shapley_rows=shapley,
        current_weights=current,
        new_promotion_ts_utc=ts,
    )
    by_desk = {p.desk_name: p.weight for p in proposal}
    assert by_desk["a"] == pytest.approx(1.0)
    assert by_desk["b"] == pytest.approx(0.0)


def test_propose_preserves_weight_for_desk_absent_from_shapley():
    ts = datetime(2026, 4, 20, 16, 30, 0, tzinfo=UTC)
    current = _current_weights_stub([("a", 0.3), ("b", 0.3), ("new_desk", 0.4)])
    shapley = [_shapley("a", 80.0, ts), _shapley("b", 20.0, ts)]
    proposal = propose_weights_from_shapley(
        shapley_rows=shapley,
        current_weights=current,
        new_promotion_ts_utc=ts,
    )
    by_desk = {p.desk_name: p.weight for p in proposal}
    # a, b rescale proportionally; new_desk keeps 0.4.
    assert by_desk["a"] == pytest.approx(0.8)
    assert by_desk["b"] == pytest.approx(0.2)
    assert by_desk["new_desk"] == pytest.approx(0.4)


def test_propose_all_zero_shapley_preserves_current_weights():
    ts = datetime(2026, 4, 20, 16, 30, 0, tzinfo=UTC)
    current = _current_weights_stub([("a", 0.33), ("b", 0.33), ("c", 0.34)])
    shapley = [_shapley(d, 0.0, ts) for d, _ in [("a", 0), ("b", 0), ("c", 0)]]
    proposal = propose_weights_from_shapley(
        shapley_rows=shapley,
        current_weights=current,
        new_promotion_ts_utc=ts,
    )
    by_desk = {p.desk_name: p.weight for p in proposal}
    assert by_desk["a"] == pytest.approx(0.33)
    assert by_desk["b"] == pytest.approx(0.33)
    assert by_desk["c"] == pytest.approx(0.34)


def test_propose_rejects_naive_promotion_ts():
    current = _current_weights_stub([("a", 1.0)])
    shapley = [_shapley("a", 1.0, datetime(2026, 4, 20, 16, tzinfo=UTC))]
    with pytest.raises(ValueError, match="timezone-aware"):
        propose_weights_from_shapley(
            shapley_rows=shapley,
            current_weights=current,
            new_promotion_ts_utc=datetime(2026, 4, 20, 16),
        )


# ---------------------------------------------------------------------------
# Integration: promotion is visible to the next Controller decision
# ---------------------------------------------------------------------------


def test_promotion_takes_effect_on_next_controller_decide(conn):
    boot = datetime(2026, 4, 16, 9, 0, 0, tzinfo=UTC)
    t_review = datetime(2026, 4, 20, 16, 30, 0, tzinfo=UTC)
    t_decide = datetime(2026, 4, 20, 17, 0, 0, tzinfo=UTC)

    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("macro", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=boot,
        default_cold_start_limit=1000.0,
    )

    # Propose + promote: storage dominates 9:1.
    shapley = [
        _shapley("storage_curve", 90.0, t_review),
        _shapley("macro", 10.0, t_review),
    ]
    propose_and_promote_from_shapley(
        conn=conn,
        regime_id="regime_boot",
        shapley_rows=shapley,
        new_promotion_ts_utc=t_review,
    )

    # Controller now reads the new weights.
    ws = get_latest_signal_weights(conn, "regime_boot")
    by_desk = {r["desk_name"]: r["weight"] for r in ws}
    assert by_desk["storage_curve"] == pytest.approx(0.9)
    assert by_desk["macro"] == pytest.approx(0.1)
    # validation_artefact marks the promotion as the Shapley-v0.2 path.
    artefacts = {r["validation_artefact"] for r in ws}
    assert PROMOTION_ARTEFACT_SHAPLEY_V02 in artefacts

    # Controller uses the new weights on the next decision.
    ctrl = Controller(conn=conn)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 100.0, t_decide),
        ("macro", WTI_FRONT_MONTH_CLOSE): _fcast("macro", 100.0, t_decide),
    }
    d = ctrl.decide(now_utc=t_decide, regime_label=_regime(t_decide), recent_forecasts=recent)
    # combined = 0.9 * 100 + 0.1 * 100 = 100 (reweighting doesn't change
    # equal-forecast case), but with 60/40 forecast it would. Test the
    # non-trivial case too.
    assert d.combined_signal == pytest.approx(100.0)

    recent2 = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 100.0, t_decide),
        ("macro", WTI_FRONT_MONTH_CLOSE): _fcast("macro", 50.0, t_decide),
    }
    d2 = ctrl.decide(now_utc=t_decide, regime_label=_regime(t_decide), recent_forecasts=recent2)
    # Under post-promotion weights 0.9 / 0.1:
    # combined = 0.9 * 100 + 0.1 * 50 = 95
    # Under cold-start weights 0.5 / 0.5 this would have been 75.
    assert d2.combined_signal == pytest.approx(95.0)
