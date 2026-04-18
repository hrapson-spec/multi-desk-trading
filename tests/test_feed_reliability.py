"""Tests for Layer 2 of the feed-reliability learning loop (spec §14.5,
§7.2 parity).

Covers:
  - Rolling failure-rate counts + currently-open filter.
  - Retirement threshold across ALL regimes (not just active).
  - Bounded retirement cap that defers overshoot to next tick.
  - Reinstatement eligibility (recovery window, not currently open).
  - Direct reinstatement fallback when Shapley can't fire.
  - retired_desks_for_feed + active_target_variables_for_desk helpers.
  - End-to-end handler: open → review → retire → close → review →
    reinstate.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import ResearchLoopEvent
from controller import seed_cold_start
from persistence import (
    close_feed_incident,
    connect,
    get_latest_signal_weights,
    init_db,
    open_feed_incident,
)
from research_loop import (
    FEED_RELIABILITY_HANDLER_V02,
    FEED_UNRELIABLE_PREFIX,
    REINSTATE_PREFIX,
    active_target_variables_for_desk,
    compute_feed_failure_rate,
    count_recent_auto_retirements,
    feed_reliability_review_handler,
    feeds_eligible_for_reinstatement,
    feeds_meeting_retirement_criteria,
    reinstate_desk_direct,
    retire_desk_for_all_regimes,
    retired_desks_for_feed,
)

NOW = datetime(2026, 4, 17, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path):
    c = connect(tmp_path / "fr.duckdb")
    init_db(c)
    yield c
    c.close()


def _seed_two_regimes_with_desks(conn, desk_names: list[str]) -> None:
    seed_cold_start(
        conn,
        desks=[(name, WTI_FRONT_MONTH_CLOSE) for name in desk_names],
        regime_ids=["regime_boot", "regime_contango"],
        boot_ts=NOW - timedelta(days=90),
        default_cold_start_limit=1000.0,
    )


def _fire_incident(
    conn,
    *,
    feed_name: str,
    ts: datetime,
    affected_desks: list[str],
    close_after: timedelta | None = None,
) -> str:
    fid = open_feed_incident(
        conn,
        feed_name=feed_name,
        opened_ts_utc=ts,
        affected_desks=affected_desks,
        detected_by="scheduler",
    )
    if close_after is not None:
        close_feed_incident(
            conn,
            feed_incident_id=fid,
            closed_ts_utc=ts + close_after,
            resolution_artefact="auto:test_close",
        )
    return fid


# ---------------------------------------------------------------------------
# compute_feed_failure_rate
# ---------------------------------------------------------------------------


def test_compute_feed_failure_rate_counts_within_window(conn):
    # 3 incidents in the last 30 days, 1 outside.
    for i, days_back in enumerate([1, 5, 12]):
        _fire_incident(
            conn,
            feed_name="eia_wpsr",
            ts=NOW - timedelta(days=days_back, hours=i),
            affected_desks=["supply"],
            close_after=timedelta(hours=1),
        )
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(days=60),
        affected_desks=["supply"],
        close_after=timedelta(hours=1),
    )
    stats = compute_feed_failure_rate(conn, feed_name="eia_wpsr", lookback_days=30, now_utc=NOW)
    assert stats.failure_count_window == 3
    assert stats.currently_open is False
    assert stats.last_failure_ts_utc == NOW - timedelta(days=1, hours=0)


def test_compute_feed_failure_rate_reports_currently_open(conn):
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(hours=1),
        affected_desks=["supply"],
    )
    stats = compute_feed_failure_rate(conn, feed_name="eia_wpsr", lookback_days=30, now_utc=NOW)
    assert stats.currently_open is True
    assert stats.failure_count_window == 1


# ---------------------------------------------------------------------------
# feeds_meeting_retirement_criteria
# ---------------------------------------------------------------------------


def test_retirement_requires_both_threshold_and_open_incident(conn):
    """Historically-flaky feed with zero open incidents is NOT a
    retirement candidate — that's reinstatement territory."""
    for i in range(6):
        _fire_incident(
            conn,
            feed_name="eia_wpsr",
            ts=NOW - timedelta(days=i + 1),
            affected_desks=["supply"],
            close_after=timedelta(hours=1),
        )
    assert (
        feeds_meeting_retirement_criteria(
            conn,
            feed_names=["eia_wpsr"],
            lookback_days=30,
            threshold_failures=5,
            now_utc=NOW,
        )
        == []
    )


def test_retirement_fires_when_threshold_met_and_incident_open(conn):
    for i in range(4):
        _fire_incident(
            conn,
            feed_name="eia_wpsr",
            ts=NOW - timedelta(days=i + 2),
            affected_desks=["supply"],
            close_after=timedelta(hours=1),
        )
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(hours=1),
        affected_desks=["supply"],
    )
    hits = feeds_meeting_retirement_criteria(
        conn,
        feed_names=["eia_wpsr"],
        lookback_days=30,
        threshold_failures=5,
        now_utc=NOW,
    )
    assert len(hits) == 1
    assert hits[0].feed_name == "eia_wpsr"
    assert hits[0].failure_count_window == 5


# ---------------------------------------------------------------------------
# retire_desk_for_all_regimes (core primitive)
# ---------------------------------------------------------------------------


def test_retire_all_regimes_zeros_weight_in_both_regimes(conn):
    _seed_two_regimes_with_desks(conn, ["supply", "macro"])
    # Sanity: supply has 0.5 in both regimes (uniform prior).
    w_before_boot = {
        r["desk_name"]: r["weight"] for r in get_latest_signal_weights(conn, "regime_boot")
    }
    w_before_cont = {
        r["desk_name"]: r["weight"] for r in get_latest_signal_weights(conn, "regime_contango")
    }
    assert w_before_boot["supply"] == pytest.approx(0.5)
    assert w_before_cont["supply"] == pytest.approx(0.5)

    written = retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    assert len(written) == 2
    assert all(sw.weight == 0.0 for sw in written)
    assert all(sw.validation_artefact == f"{FEED_UNRELIABLE_PREFIX}eia_wpsr" for sw in written)

    w_after_boot = {
        r["desk_name"]: r["weight"] for r in get_latest_signal_weights(conn, "regime_boot")
    }
    w_after_cont = {
        r["desk_name"]: r["weight"] for r in get_latest_signal_weights(conn, "regime_contango")
    }
    assert w_after_boot["supply"] == pytest.approx(0.0)
    assert w_after_cont["supply"] == pytest.approx(0.0)
    # Macro preserved.
    assert w_after_boot["macro"] == pytest.approx(0.5)
    assert w_after_cont["macro"] == pytest.approx(0.5)


def test_retire_all_regimes_noop_when_nothing_to_retire(conn):
    """retire_desk_for_all_regimes returns [] when the desk is already
    at zero / absent — safe under idempotency retries."""
    # No seed → no rows exist.
    written = retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    assert written == []


def test_retire_all_regimes_rejects_naive_ts(conn):
    with pytest.raises(ValueError, match="timezone-aware"):
        retire_desk_for_all_regimes(
            conn,
            desk_name="supply",
            target_variable=WTI_FRONT_MONTH_CLOSE,
            reason="eia_wpsr",
            now_utc=datetime(2026, 4, 17),
        )


# ---------------------------------------------------------------------------
# reinstate_desk_direct
# ---------------------------------------------------------------------------


def test_reinstate_direct_writes_nonzero_weight(conn):
    _seed_two_regimes_with_desks(conn, ["supply"])
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW - timedelta(days=20),
    )
    # After retire, supply weight is 0 in both regimes.
    assert get_latest_signal_weights(conn, "regime_boot")[0]["weight"] == pytest.approx(0.0)

    sw = reinstate_desk_direct(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        weight=0.1,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    assert sw.weight == pytest.approx(0.1)
    assert sw.validation_artefact == f"{REINSTATE_PREFIX}eia_wpsr"

    after = get_latest_signal_weights(conn, "regime_boot")
    live = {r["desk_name"]: r for r in after}
    assert live["supply"]["weight"] == pytest.approx(0.1)
    assert live["supply"]["validation_artefact"] == f"{REINSTATE_PREFIX}eia_wpsr"


def test_reinstate_direct_rejects_negative_weight(conn):
    with pytest.raises(ValueError, match="weight must be"):
        reinstate_desk_direct(
            conn,
            regime_id="regime_boot",
            desk_name="supply",
            target_variable=WTI_FRONT_MONTH_CLOSE,
            weight=-0.1,
            reason="eia_wpsr",
            now_utc=NOW,
        )


# ---------------------------------------------------------------------------
# count_recent_auto_retirements (cap primitive)
# ---------------------------------------------------------------------------


def test_count_recent_auto_retirements_distinct_triples(conn):
    _seed_two_regimes_with_desks(conn, ["supply", "demand"])
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    retire_desk_for_all_regimes(
        conn,
        desk_name="demand",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW + timedelta(minutes=5),
    )
    # 2 desks × 2 regimes × 1 target = 4 distinct triples.
    count = count_recent_auto_retirements(
        conn, prefix=FEED_UNRELIABLE_PREFIX, window_days=7, now_utc=NOW + timedelta(hours=1)
    )
    assert count == 4


def test_count_recent_auto_retirements_excludes_old(conn):
    _seed_two_regimes_with_desks(conn, ["supply"])
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW - timedelta(days=30),
    )
    count = count_recent_auto_retirements(
        conn, prefix=FEED_UNRELIABLE_PREFIX, window_days=7, now_utc=NOW
    )
    assert count == 0


# ---------------------------------------------------------------------------
# feeds_eligible_for_reinstatement
# ---------------------------------------------------------------------------


def test_reinstatement_eligible_when_no_recent_failures_and_not_open(conn):
    # A failure 30 days ago, closed, no recent issues.
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(days=30),
        affected_desks=["supply"],
        close_after=timedelta(hours=1),
    )
    assert feeds_eligible_for_reinstatement(
        conn, feed_names=["eia_wpsr"], recovery_days=14, now_utc=NOW
    ) == ["eia_wpsr"]


def test_reinstatement_ineligible_if_currently_open(conn):
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(hours=1),
        affected_desks=["supply"],
    )
    assert (
        feeds_eligible_for_reinstatement(
            conn, feed_names=["eia_wpsr"], recovery_days=14, now_utc=NOW
        )
        == []
    )


def test_reinstatement_ineligible_if_recent_failure_even_if_closed(conn):
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(days=3),
        affected_desks=["supply"],
        close_after=timedelta(hours=1),
    )
    assert (
        feeds_eligible_for_reinstatement(
            conn, feed_names=["eia_wpsr"], recovery_days=14, now_utc=NOW
        )
        == []
    )


# ---------------------------------------------------------------------------
# retired_desks_for_feed
# ---------------------------------------------------------------------------


def test_retired_desks_for_feed_returns_latest_zero_only(conn):
    _seed_two_regimes_with_desks(conn, ["supply", "demand"])
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    retired = retired_desks_for_feed(conn, feed_name="eia_wpsr")
    assert len(retired) == 2
    assert all(r[1] == "supply" for r in retired)
    # demand is still at 0.5, not retired for this feed.
    assert all(r[1] != "demand" for r in retired)


def test_retired_desks_for_feed_excludes_reinstated(conn):
    _seed_two_regimes_with_desks(conn, ["supply"])
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW - timedelta(days=5),
    )
    # Reinstate in regime_boot only.
    reinstate_desk_direct(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        weight=0.1,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    retired = retired_desks_for_feed(conn, feed_name="eia_wpsr")
    # regime_boot reinstated → not retired any more. regime_contango still at 0.
    assert len(retired) == 1
    assert retired[0][0] == "regime_contango"


# ---------------------------------------------------------------------------
# active_target_variables_for_desk
# ---------------------------------------------------------------------------


def test_active_targets_returns_only_nonzero(conn):
    _seed_two_regimes_with_desks(conn, ["supply"])
    assert active_target_variables_for_desk(conn, "supply") == [WTI_FRONT_MONTH_CLOSE]
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW,
    )
    assert active_target_variables_for_desk(conn, "supply") == []


# ---------------------------------------------------------------------------
# feed_reliability_review_handler (end-to-end)
# ---------------------------------------------------------------------------


def _review_event(**payload):
    return ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="feed_reliability_review",
        triggered_at_utc=NOW,
        priority=1,
        payload=payload,
    )


def test_handler_requires_feed_names(conn):
    result = feed_reliability_review_handler(conn, _review_event())
    data = json.loads(result.artefact)
    assert "error" in data


def test_handler_rejects_wrong_event_type(conn):
    event = ResearchLoopEvent(
        event_id=str(uuid.uuid4()),
        event_type="gate_failure",
        triggered_at_utc=NOW,
        priority=1,
        payload={"feed_names": ["eia_wpsr"]},
    )
    with pytest.raises(ValueError, match="wrong event"):
        feed_reliability_review_handler(conn, event)


def test_handler_retires_when_threshold_met(conn):
    _seed_two_regimes_with_desks(conn, ["supply", "macro"])
    # 4 closed + 1 open incident in the lookback → threshold_failures=5 met.
    for i in range(4):
        _fire_incident(
            conn,
            feed_name="eia_wpsr",
            ts=NOW - timedelta(days=i + 2),
            affected_desks=["supply"],
            close_after=timedelta(hours=1),
        )
    _fire_incident(
        conn,
        feed_name="eia_wpsr",
        ts=NOW - timedelta(hours=1),
        affected_desks=["supply"],
    )
    result = feed_reliability_review_handler(conn, _review_event(feed_names=["eia_wpsr"]))
    data = json.loads(result.artefact)
    assert data["handler"] == FEED_RELIABILITY_HANDLER_V02
    assert len(data["retirements_performed"]) == 2  # 2 regimes × 1 target × 1 desk
    assert data["cap_reached"] is False

    # Controller's next read: supply weight is 0 in both regimes.
    for regime in ("regime_boot", "regime_contango"):
        live = {r["desk_name"]: r["weight"] for r in get_latest_signal_weights(conn, regime)}
        assert live["supply"] == pytest.approx(0.0)
        assert live["macro"] == pytest.approx(0.5)


def test_handler_cap_limits_retirements(conn):
    _seed_two_regimes_with_desks(conn, ["supply", "demand"])
    # Arrange: 2 feeds both meeting retirement threshold, each with 2
    # affected desks. Without cap → 4 desk × 2 regimes = 8 triples.
    for feed, desk in [("eia_wpsr", "supply"), ("fomc_statement", "demand")]:
        for i in range(5):
            _fire_incident(
                conn,
                feed_name=feed,
                ts=NOW - timedelta(days=i + 2, minutes=hash(feed) % 50),
                affected_desks=[desk],
                close_after=timedelta(hours=1),
            )
        _fire_incident(
            conn,
            feed_name=feed,
            ts=NOW - timedelta(hours=1),
            affected_desks=[desk],
        )
    result = feed_reliability_review_handler(
        conn,
        _review_event(
            feed_names=["eia_wpsr", "fomc_statement"],
            max_retirements_per_7_days=2,
        ),
    )
    data = json.loads(result.artefact)
    # Cap = 2. First feed consumes budget = 2 (both regimes for supply).
    # Second feed's retirements go into retirements_skipped_capped.
    assert len(data["retirements_performed"]) == 2
    assert len(data["retirements_skipped_capped"]) >= 1
    assert data["cap_reached"] is True


def test_handler_reinstates_on_recovered_feed(conn):
    _seed_two_regimes_with_desks(conn, ["supply"])
    # Retire supply now (simulating prior review).
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW - timedelta(days=30),
    )
    # No incidents in the recovery window → feed eligible.
    result = feed_reliability_review_handler(
        conn,
        _review_event(feed_names=["eia_wpsr"], recovery_days=14, reinstate_weight=0.1),
    )
    data = json.loads(result.artefact)
    assert data["reinstatement_fallbacks"] == []
    assert len(data["reinstatements_performed"]) == 2
    # Historical-weight fallback restores the last live weight. With only one
    # active desk in the cold-start bundle, that weight is 1.0.
    for regime in ("regime_boot", "regime_contango"):
        live = {r["desk_name"]: r["weight"] for r in get_latest_signal_weights(conn, regime)}
        assert live["supply"] == pytest.approx(1.0)


def test_handler_no_op_when_nothing_qualifies(conn):
    _seed_two_regimes_with_desks(conn, ["supply"])
    result = feed_reliability_review_handler(conn, _review_event(feed_names=["eia_wpsr"]))
    data = json.loads(result.artefact)
    assert data["retirements_performed"] == []
    assert data["reinstatement_fallbacks"] == []
    assert data["cap_reached"] is False


# ---------------------------------------------------------------------------
# historical_shapley_share + Shapley-informed reinstatement path
# ---------------------------------------------------------------------------


def _seed_shapley_row(
    conn,
    *,
    review_ts_utc: datetime,
    desk_name: str,
    shapley_value: float,
) -> None:
    import uuid as _uuid

    from contracts.v1 import AttributionShapley
    from persistence import insert_attribution_shapley

    insert_attribution_shapley(
        conn,
        AttributionShapley(
            attribution_id=str(_uuid.uuid4()),
            review_ts_utc=review_ts_utc,
            desk_name=desk_name,
            shapley_value=shapley_value,
            metric_name="combined_signal_marginal",
            n_decisions=1,
            coalitions_mode="exact",
        ),
    )


def test_historical_shapley_share_empty_when_no_rows(conn):
    from research_loop import historical_shapley_share

    assert historical_shapley_share(conn, desk_name="supply", lookback_days=90, now_utc=NOW) is None


def test_historical_shapley_share_computes_mean_share(conn):
    from research_loop import historical_shapley_share

    # Review 1: supply=10, macro=30 → supply share = 10/40 = 0.25
    # Review 2: supply=20, macro=20 → supply share = 20/40 = 0.50
    review1_ts = NOW - timedelta(days=14)
    review2_ts = NOW - timedelta(days=7)
    for ts, supply_v, macro_v in [
        (review1_ts, 10.0, 30.0),
        (review2_ts, 20.0, 20.0),
    ]:
        _seed_shapley_row(conn, review_ts_utc=ts, desk_name="supply", shapley_value=supply_v)
        _seed_shapley_row(conn, review_ts_utc=ts, desk_name="macro", shapley_value=macro_v)

    share = historical_shapley_share(conn, desk_name="supply", lookback_days=30, now_utc=NOW)
    assert share is not None
    # Mean of [0.25, 0.50] = 0.375.
    assert share == pytest.approx(0.375)


def test_historical_shapley_share_respects_lookback(conn):
    from research_loop import historical_shapley_share

    old_ts = NOW - timedelta(days=120)
    _seed_shapley_row(conn, review_ts_utc=old_ts, desk_name="supply", shapley_value=10.0)
    _seed_shapley_row(conn, review_ts_utc=old_ts, desk_name="macro", shapley_value=10.0)
    # Lookback = 30 days → the 120d-old row is out of window.
    assert historical_shapley_share(conn, desk_name="supply", lookback_days=30, now_utc=NOW) is None


def test_handler_reinstatement_prefers_shapley_share(conn):
    """With Shapley rows available, reinstatement uses the historical
    share and populates reinstatements_performed (not fallbacks)."""
    _seed_two_regimes_with_desks(conn, ["supply"])
    # Retire supply (simulating prior review).
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW - timedelta(days=30),
    )
    # Seed Shapley rows giving supply a 40% historical share.
    review_ts = NOW - timedelta(days=10)
    _seed_shapley_row(conn, review_ts_utc=review_ts, desk_name="supply", shapley_value=40.0)
    _seed_shapley_row(conn, review_ts_utc=review_ts, desk_name="macro", shapley_value=60.0)

    result = feed_reliability_review_handler(
        conn,
        _review_event(feed_names=["eia_wpsr"], recovery_days=14, reinstate_weight=0.1),
    )
    data = json.loads(result.artefact)
    # Shapley-informed path populates reinstatements_performed, not fallbacks.
    assert len(data["reinstatements_performed"]) == 2  # both regimes
    assert data["reinstatement_fallbacks"] == []
    for record in data["reinstatements_performed"]:
        assert record["source"] == "shapley"
        # Supply's historical share = 40/100 = 0.4
        assert record["weight"] == pytest.approx(0.4)


def test_handler_uses_historical_weight_when_no_shapley_rows(conn):
    """Without Shapley rows, reinstatement falls back to the last known
    positive weight for the retired desk-regime pair."""
    _seed_two_regimes_with_desks(conn, ["supply"])
    retire_desk_for_all_regimes(
        conn,
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="eia_wpsr",
        now_utc=NOW - timedelta(days=30),
    )
    result = feed_reliability_review_handler(
        conn,
        _review_event(feed_names=["eia_wpsr"], recovery_days=14, reinstate_weight=0.15),
    )
    data = json.loads(result.artefact)
    assert data["reinstatement_fallbacks"] == []
    assert len(data["reinstatements_performed"]) == 2
    for record in data["reinstatements_performed"]:
        assert record["source"] == "historical_weight"
        assert record["weight"] == pytest.approx(1.0)
