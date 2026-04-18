"""Tests for research_loop.handlers.regime_transition_handler v0.3.

v0.3 contract: on regime transition, look up historical decisions and
matching realised Prints for the to_regime in a lookback window; if
≥min_decisions exist, compute grading-space Shapley, run the held-out
margin validation, and promote only when the candidate beats the
incumbent. Otherwise fall back to log-only.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Print,
    Provenance,
    RegimeLabel,
    ResearchLoopEvent,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from persistence import (
    connect,
    get_latest_signal_weights,
    init_db,
    insert_decision,
    insert_forecast,
    insert_print,
)
from research_loop.handlers import (
    REGIME_TRANSITION_ARTEFACT_V03,
    regime_transition_handler,
)

TO_REGIME = "regime_contango"
FROM_REGIME = "regime_boot"
BOOT = datetime(2026, 3, 1, 0, 0, 0, tzinfo=UTC)
TRANSITION_TS = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "rt.duckdb")
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


def _regime_label(ts: datetime, regime_id: str) -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=ts,
        regime_id=regime_id,
        regime_probabilities={regime_id: 1.0},
        transition_probabilities={regime_id: 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def _seed_history_for_to_regime(conn, n_decisions: int) -> list[datetime]:
    """Seed signal_weights + n_decisions historical decisions tagged
    with TO_REGIME. Returns the decision timestamps."""
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("macro", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=[FROM_REGIME, TO_REGIME],
        boot_ts=BOOT,
        default_cold_start_limit=1000.0,
    )
    ctrl = Controller(conn=conn)
    ts_list: list[datetime] = []
    for i in range(n_decisions):
        # Decisions scattered in the week leading up to the transition,
        # but still inside the default 30-day lookback window.
        ts = TRANSITION_TS - timedelta(days=i + 1)
        ts_list.append(ts)
        storage_val = 45.0 + 8.0 * i
        # Macro is intentionally higher-scale but noisier / less aligned with
        # the realised print path, so the normalized grading-space Shapley
        # candidate should shift weight toward storage_curve and beat the
        # incumbent equal-weight bundle on held-out MSE.
        macro_val = 82.0 + 2.0 * i + (14.0 if i % 2 == 0 else -11.0)
        fcasts = {
            ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", storage_val, ts),
            ("macro", WTI_FRONT_MONTH_CLOSE): _fcast("macro", macro_val, ts),
        }
        for f in fcasts.values():
            insert_forecast(conn, f)
        d = ctrl.decide(
            now_utc=ts,
            regime_label=_regime_label(ts, TO_REGIME),
            recent_forecasts=fcasts,
        )
        insert_decision(conn, d)
        insert_print(
            conn,
            Print(
                print_id=f"print-{i}",
                realised_ts_utc=ts,
                target_variable=WTI_FRONT_MONTH_CLOSE,
                value=storage_val,
            ),
        )
    return ts_list


# ---------------------------------------------------------------------------
# Payload-validation paths (shared between v0.1 and v0.2 contract)
# ---------------------------------------------------------------------------


def test_regime_transition_rejects_wrong_event_type(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="periodic_weekly",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={},
    )
    with pytest.raises(ValueError, match="wrong event"):
        regime_transition_handler(conn, event)


def test_regime_transition_missing_payload_returns_error_artefact(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={"from_regime": "a"},  # missing to_regime + probability
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    assert "error" in data
    assert "missing payload keys" in data["error"]


# ---------------------------------------------------------------------------
# v0.2 path: insufficient history → fail-safe
# ---------------------------------------------------------------------------


def test_no_history_for_to_regime_is_insufficient(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={
            "from_regime": FROM_REGIME,
            "to_regime": TO_REGIME,
            "probability": 0.9,
        },
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["handler"] == "regime_transition_v0.3"
    assert data["action"] == "insufficient_history_for_refresh"
    assert data["refresh_detail"]["n_decisions"] == 0
    # No signal_weights rows should have been written (cold-start not
    # seeded either, so table is empty).
    rows = conn.execute("SELECT count(*) FROM signal_weights").fetchone()
    assert rows[0] == 0


def test_below_min_decisions_is_insufficient(conn):
    # Seed only 3 decisions; default min_decisions=5.
    _seed_history_for_to_regime(conn, n_decisions=3)
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={
            "from_regime": FROM_REGIME,
            "to_regime": TO_REGIME,
            "probability": 0.85,
        },
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["action"] == "insufficient_history_for_refresh"
    assert data["refresh_detail"]["n_decisions"] == 3
    assert data["refresh_detail"]["min_required"] == 5

    # No new SignalWeight rows tagged with REGIME_TRANSITION_ARTEFACT_V03.
    rows = conn.execute(
        "SELECT count(*) FROM signal_weights WHERE validation_artefact = ?",
        [REGIME_TRANSITION_ARTEFACT_V03],
    ).fetchone()
    assert rows[0] == 0


# ---------------------------------------------------------------------------
# v0.2 path: sufficient history → Shapley refresh
# ---------------------------------------------------------------------------


def test_sufficient_history_triggers_validated_refresh(conn):
    _seed_history_for_to_regime(conn, n_decisions=6)
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={
            "from_regime": FROM_REGIME,
            "to_regime": TO_REGIME,
            "probability": 0.95,
        },
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["action"] == "refreshed_from_validated_shapley"
    assert data["refresh_detail"]["n_decisions"] == 6
    assert data["refresh_detail"]["n_prints"] == 6
    assert data["refresh_detail"]["validation_artefact"] == REGIME_TRANSITION_ARTEFACT_V03
    assert data["refresh_detail"]["validation"]["passed"] is True
    # Exactly two desks promoted (storage_curve + macro).
    assert data["refresh_detail"]["n_desks_promoted"] == 2

    # New SignalWeight rows exist for TO_REGIME tagged with the v0.3 artefact.
    rows = conn.execute(
        """
        SELECT desk_name, weight, validation_artefact
        FROM signal_weights
        WHERE regime_id = ? AND validation_artefact = ?
        ORDER BY desk_name
        """,
        [TO_REGIME, REGIME_TRANSITION_ARTEFACT_V03],
    ).fetchall()
    assert len(rows) == 2
    desk_weights = {r[0]: r[1] for r in rows}
    # Weights are normalised to sum to 1 across desks.
    assert sum(desk_weights.values()) == pytest.approx(1.0, abs=1e-9)
    # Both weights are >= 0 (Shapley-proportional rules).
    assert all(w >= 0.0 for w in desk_weights.values())

    # The Controller's live read (latest row per desk) now picks the v0.3 bundle.
    live = get_latest_signal_weights(conn, TO_REGIME)
    live_by_desk = {r["desk_name"]: r for r in live}
    assert live_by_desk["storage_curve"]["validation_artefact"] == REGIME_TRANSITION_ARTEFACT_V03
    assert live_by_desk["macro"]["validation_artefact"] == REGIME_TRANSITION_ARTEFACT_V03


def test_custom_min_decisions_overrides_default(conn):
    """With min_decisions=2, even 3 decisions triggers a refresh."""
    _seed_history_for_to_regime(conn, n_decisions=3)
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={
            "from_regime": FROM_REGIME,
            "to_regime": TO_REGIME,
            "probability": 0.8,
            "min_decisions": 2,
        },
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["action"] == "refreshed_from_validated_shapley"
    assert data["refresh_detail"]["n_decisions"] == 3


def test_narrow_lookback_excludes_older_decisions(conn):
    """Lookback of 1 hour against decisions spread over multiple days
    filters all of them out → insufficient_history path."""
    _seed_history_for_to_regime(conn, n_decisions=10)
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={
            "from_regime": FROM_REGIME,
            "to_regime": TO_REGIME,
            "probability": 0.9,
            "lookback_window_s": 3600.0,  # 1 hour
        },
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    assert data["action"] == "insufficient_history_for_refresh"
    assert data["refresh_detail"]["n_decisions"] == 0
    assert data["refresh_detail"]["lookback_window_s"] == pytest.approx(3600.0)


def test_refresh_only_counts_to_regime_decisions(conn):
    """Decisions from from_regime must not be counted toward to_regime's
    history — that would leak cross-regime evidence."""
    # Seed 6 decisions for TO_REGIME (will trigger refresh by itself),
    # then add 10 for FROM_REGIME that must NOT be counted.
    _seed_history_for_to_regime(conn, n_decisions=6)
    ctrl = Controller(conn=conn)
    for i in range(10):
        ts = TRANSITION_TS - timedelta(days=i + 1, hours=1)
        fcasts = {
            ("storage_curve", WTI_FRONT_MONTH_CLOSE): _fcast("storage_curve", 100.0, ts),
            ("macro", WTI_FRONT_MONTH_CLOSE): _fcast("macro", 50.0, ts),
        }
        for f in fcasts.values():
            insert_forecast(conn, f)
        d = ctrl.decide(
            now_utc=ts,
            regime_label=_regime_label(ts, FROM_REGIME),
            recent_forecasts=fcasts,
        )
        insert_decision(conn, d)

    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="regime_transition",
        triggered_at_utc=TRANSITION_TS,
        priority=1,
        payload={
            "from_regime": FROM_REGIME,
            "to_regime": TO_REGIME,
            "probability": 0.9,
        },
    )
    result = regime_transition_handler(conn, event)
    data = json.loads(result.artefact)
    # Must count ONLY the 6 TO_REGIME decisions, not 6 + 10.
    assert data["refresh_detail"]["n_decisions"] == 6
    assert data["action"] == "refreshed_from_validated_shapley"
