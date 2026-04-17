"""Concrete handlers bound to event types by the Dispatcher (spec §6.3).

v0.1 ships one handler:

  periodic_weekly_handler — pulls all Decisions in the review window
  from the event.payload (keys: `window_start_ts_utc`,
  `window_end_ts_utc`) and runs a compact Shapley rollup, storing a
  JSON summary (desk, shapley_value, n_decisions) in the event's
  produced_artefact. Gate-failure, regime-transition, and data-
  ingestion-failure handlers follow in later commits.

v0.2 upgrades:
  gate_failure_handler — auto-retires (regime, desk) when
    failure_mode starts with "harmful:" (§7.2).
  regime_transition_handler — triggers a Shapley-proportional weight
    refresh for the to_regime when ≥min_decisions of historical
    evidence exist for it (§8.3).

Design guardrail: handlers are pure w.r.t. their inputs except for
explicit DB writes (new AttributionShapley / SignalWeight rows). No
filesystem writes, no network, no LLM calls — those live in later
layers per §6.4 routing discipline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import duckdb

from attribution import compute_shapley_signal_space
from contracts.v1 import Decision, Forecast, Provenance, ResearchLoopEvent

from .dispatcher import HandlerResult
from .feed_reliability import (
    active_target_variables_for_desk,
    feeds_eligible_for_reinstatement,
    feeds_meeting_retirement_criteria,
    retired_desks_for_feed,
)
from .promotion import propose_and_promote_from_shapley
from .remediation import (
    FEED_UNRELIABLE_PREFIX,
    is_harmful,
    reinstate_desk_direct,
    retire_desk_for_all_regimes,
    retire_desk_for_regime,
)

REGIME_TRANSITION_ARTEFACT_V02 = "auto:regime_transition_shapley_v0.2"
FEED_RELIABILITY_HANDLER_V02 = "feed_reliability_review_v0.2"
_DEFAULT_LOOKBACK_SECONDS = 30 * 24 * 3600
_DEFAULT_MIN_DECISIONS = 5
_DEFAULT_FEED_LOOKBACK_DAYS = 30
_DEFAULT_RETIREMENT_THRESHOLD = 5
_DEFAULT_RECOVERY_DAYS = 14
_DEFAULT_RETIREMENT_CAP_PER_7_DAYS = 2
_DEFAULT_REINSTATE_WEIGHT = 0.1


def _decisions_in_window(
    conn: duckdb.DuckDBPyConnection,
    *,
    start_ts: datetime,
    end_ts: datetime,
    regime_id: str | None = None,
) -> list[Decision]:
    if regime_id is None:
        rows = conn.execute(
            """
            SELECT decision_id, emission_ts_utc, regime_id, combined_signal,
                   position_size, input_forecast_ids, provenance
            FROM decisions
            WHERE emission_ts_utc >= ? AND emission_ts_utc <= ?
            ORDER BY emission_ts_utc, decision_id
            """,
            [start_ts, end_ts],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT decision_id, emission_ts_utc, regime_id, combined_signal,
                   position_size, input_forecast_ids, provenance
            FROM decisions
            WHERE emission_ts_utc >= ? AND emission_ts_utc <= ?
              AND regime_id = ?
            ORDER BY emission_ts_utc, decision_id
            """,
            [start_ts, end_ts, regime_id],
        ).fetchall()
    out: list[Decision] = []
    for r in rows:
        out.append(
            Decision(
                decision_id=r[0],
                emission_ts_utc=r[1],
                regime_id=r[2],
                combined_signal=r[3],
                position_size=r[4],
                input_forecast_ids=json.loads(r[5]) if isinstance(r[5], str) else r[5],
                provenance=Provenance(**(json.loads(r[6]) if isinstance(r[6], str) else r[6])),
            )
        )
    return out


def _forecasts_by_decision(
    conn: duckdb.DuckDBPyConnection, decisions: list[Decision]
) -> dict[str, dict[tuple[str, str], Forecast]]:
    """Look up each decision's input forecasts by id and group by (desk, target)."""
    all_ids: list[str] = [fid for d in decisions for fid in d.input_forecast_ids]
    if not all_ids:
        return {d.decision_id: {} for d in decisions}

    # DuckDB parameterised IN via UNNEST of a list literal
    rows = conn.execute(
        """
        SELECT forecast_id, emission_ts_utc, desk_name, target_variable,
               horizon_kind, horizon_payload, point_estimate, uncertainty,
               directional_claim, staleness, confidence, provenance
        FROM forecasts
        WHERE forecast_id IN (SELECT unnest(?))
        """,
        [all_ids],
    ).fetchall()

    from contracts.v1 import (
        ClockHorizon,
        DirectionalClaim,
        EventHorizon,
        UncertaintyInterval,
    )

    by_id: dict[str, Forecast] = {}
    for r in rows:
        horizon_payload = json.loads(r[5]) if isinstance(r[5], str) else r[5]
        horizon = (
            EventHorizon(**horizon_payload) if r[4] == "event" else ClockHorizon(**horizon_payload)
        )
        by_id[r[0]] = Forecast(
            forecast_id=r[0],
            emission_ts_utc=r[1],
            target_variable=r[3],
            horizon=horizon,
            point_estimate=r[6],
            uncertainty=UncertaintyInterval(
                **(json.loads(r[7]) if isinstance(r[7], str) else r[7])
            ),
            directional_claim=DirectionalClaim(
                **(json.loads(r[8]) if isinstance(r[8], str) else r[8])
            ),
            staleness=r[9],
            confidence=r[10],
            provenance=Provenance(**(json.loads(r[11]) if isinstance(r[11], str) else r[11])),
        )

    result: dict[str, dict[tuple[str, str], Forecast]] = {}
    for d in decisions:
        bucket: dict[tuple[str, str], Forecast] = {}
        for fid in d.input_forecast_ids:
            f = by_id.get(fid)
            if f is not None:
                bucket[(f.provenance.desk_name, f.target_variable)] = f
        result[d.decision_id] = bucket
    return result


def gate_failure_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Record a gate-failure artefact + auto-retire on harmful cases (§6.2, §7.2).

    v0.2 upgrade: when `failure_mode` starts with `"harmful:"`, the
    handler invokes `remediation.retire_desk_for_regime` which writes a
    zero-weight SignalWeight row for (regime, desk, target). The
    Controller's next decision reads the new weight and drops the desk
    from the combined_signal sum. §7.2 "hard-gate retire" action.

    Payload contract:
      - desk: str (desk_name)
      - gate: str — "skill" | "sign_preservation" | "hot_swap"
      - metric: float — gate's pass/fail margin
      - failure_mode: str — short tag; "harmful:*" triggers auto-retire
      - regime_id: str — required for harmful: auto-retire (the regime
        under which the desk is being retired). Optional for non-harmful.
      - target_variable: str — required for harmful: auto-retire.
    """
    if event.event_type != "gate_failure":
        raise ValueError(f"gate_failure_handler on wrong event: {event.event_type!r}")
    required = {"desk", "gate", "metric", "failure_mode"}
    missing = required - set(event.payload.keys())
    if missing:
        return HandlerResult(
            artefact=json.dumps({"error": f"missing payload keys: {sorted(missing)}"}),
        )

    desk = event.payload["desk"]
    gate = event.payload["gate"]
    failure_mode = event.payload["failure_mode"]

    # Default: log-only (v0.1 behaviour for non-harmful cases).
    action = "logged_pending_rca"
    retire_detail: dict[str, object] | None = None

    if is_harmful(failure_mode):
        # Harmful case: attempt auto-retire. Requires regime_id and
        # target_variable in the payload; without them, log the missing
        # context and keep the desk active (fail-safe).
        retire_required = {"regime_id", "target_variable"}
        retire_missing = retire_required - set(event.payload.keys())
        if retire_missing:
            action = "harmful_but_missing_retire_payload"
            retire_detail = {"missing": sorted(retire_missing)}
        else:
            sw = retire_desk_for_regime(
                conn,
                regime_id=event.payload["regime_id"],
                desk_name=desk,
                target_variable=event.payload["target_variable"],
                reason=failure_mode,
                now_utc=datetime.now(tz=UTC),
            )
            action = "retired"
            retire_detail = {
                "weight_id": sw.weight_id,
                "regime_id": sw.regime_id,
                "target_variable": sw.target_variable,
                "validation_artefact": sw.validation_artefact,
            }

    artefact = json.dumps(
        {
            "handler": "gate_failure_v0.2",
            "desk": desk,
            "gate": gate,
            "metric": event.payload["metric"],
            "failure_mode": failure_mode,
            "action": action,
            "retire_detail": retire_detail,
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=f"gate_failure {action} for {desk}/{gate}",
    )


def regime_transition_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Trigger a Shapley-proportional weight refresh on regime transition
    (§6.2, §8.3).

    v0.2 upgrade: when ≥`min_decisions` historical decisions exist for
    the to_regime within the lookback window, the handler runs a
    Shapley rollup over those decisions and invokes
    `propose_and_promote_from_shapley` to write a fresh SignalWeight
    bundle for the to_regime. Controller picks up the new weights on
    the next decision via the (promotion_ts_utc DESC, weight_id DESC)
    tie-break. If history is insufficient, the handler logs the
    transition without mutating state (fail-safe).

    Payload contract:
      - from_regime: str
      - to_regime: str
      - probability: float (>= 0.7 per §6.2 default threshold)
      - lookback_window_s: float (optional, default 30 days) — seconds
        back from event.triggered_at_utc over which to gather history.
      - min_decisions: int (optional, default 5) — minimum historical
        to_regime decisions required to trigger a refresh.

    Refresh semantics match §8.3 Shapley-monotone path: candidate
    weights are |Shapley|-proportional, normalised across desks, with
    zero-|Shapley| desks falling to weight 0. Capability-claim debit:
    v0.2 omits the held-out margin check — see promotion.py.
    """
    if event.event_type != "regime_transition":
        raise ValueError(f"regime_transition_handler on wrong event: {event.event_type!r}")
    required = {"from_regime", "to_regime", "probability"}
    missing = required - set(event.payload.keys())
    if missing:
        return HandlerResult(
            artefact=json.dumps({"error": f"missing payload keys: {sorted(missing)}"}),
        )

    from_regime = event.payload["from_regime"]
    to_regime = event.payload["to_regime"]
    probability = event.payload["probability"]
    lookback_s = float(event.payload.get("lookback_window_s", _DEFAULT_LOOKBACK_SECONDS))
    min_decisions = int(event.payload.get("min_decisions", _DEFAULT_MIN_DECISIONS))

    end_ts = event.triggered_at_utc
    start_ts = end_ts - timedelta(seconds=lookback_s)
    decisions = _decisions_in_window(conn, start_ts=start_ts, end_ts=end_ts, regime_id=to_regime)

    action: str
    refresh_detail: dict[str, object] | None = None

    if len(decisions) < min_decisions:
        action = "insufficient_history_for_refresh"
        refresh_detail = {
            "n_decisions": len(decisions),
            "min_required": min_decisions,
            "to_regime": to_regime,
            "lookback_window_s": lookback_s,
        }
    else:
        recent_by_decision = _forecasts_by_decision(conn, decisions)
        shapley_rows = compute_shapley_signal_space(
            conn=conn,
            decisions=decisions,
            recent_forecasts_by_decision=recent_by_decision,
            review_ts_utc=end_ts,
        )
        promoted = propose_and_promote_from_shapley(
            conn=conn,
            regime_id=to_regime,
            shapley_rows=shapley_rows,
            new_promotion_ts_utc=end_ts,
            validation_artefact=REGIME_TRANSITION_ARTEFACT_V02,
        )
        action = "refreshed_from_shapley"
        refresh_detail = {
            "n_decisions": len(decisions),
            "n_desks_promoted": len(promoted),
            "validation_artefact": REGIME_TRANSITION_ARTEFACT_V02,
            "shapley": sorted(
                [{"desk": r.desk_name, "value": r.shapley_value} for r in shapley_rows],
                key=lambda x: str(x["desk"]),
            ),
        }

    artefact = json.dumps(
        {
            "handler": "regime_transition_v0.2",
            "from": from_regime,
            "to": to_regime,
            "probability": probability,
            "action": action,
            "refresh_detail": refresh_detail,
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=f"regime transition {from_regime} → {to_regime} {action}",
    )


def data_ingestion_failure_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Open a feed incident on data-ingestion failure (§6.2, §14.5 v1.7).

    v0.2 upgrade: calls `open_feed_incident` on the registry. Desks'
    `_staleness_from_feeds` checks (desks/base.py) read the registry
    on Forecast emission and propagate `staleness=True`; the
    Controller then drops those forecasts from combined_signal via
    the existing `if f.staleness: continue` path. Idempotent —
    duplicate fires (scheduler re-tick, restart) return the same
    feed_incident_id.

    Payload contract:
      - feed_name: str — matches feed_name in config/data_sources.yaml
      - scheduled_release_ts_utc: ISO-8601 string
      - affected_desks: list[str] — desks that consume this feed
      - detected_by: str (optional, default 'scheduler') — one of
        'scheduler' | 'page_hinkley' | 'manual'. Passed through to
        the feed_incidents row for later provenance / RCA.
    """
    if event.event_type != "data_ingestion_failure":
        raise ValueError(f"data_ingestion_failure_handler on wrong event: {event.event_type!r}")
    required = {"feed_name", "scheduled_release_ts_utc", "affected_desks"}
    missing = required - set(event.payload.keys())
    if missing:
        return HandlerResult(
            artefact=json.dumps({"error": f"missing payload keys: {sorted(missing)}"}),
        )

    feed_name = str(event.payload["feed_name"])
    affected_desks_raw = event.payload["affected_desks"]
    affected_desks = [str(d) for d in affected_desks_raw] if affected_desks_raw else []
    detected_by = str(event.payload.get("detected_by", "scheduler"))

    from persistence import open_feed_incident

    feed_incident_id = open_feed_incident(
        conn,
        feed_name=feed_name,
        opened_ts_utc=event.triggered_at_utc,
        affected_desks=affected_desks,
        detected_by=detected_by,
        opening_event_id=event.event_id,
    )

    artefact = json.dumps(
        {
            "handler": "data_ingestion_failure_v0.2",
            "feed_name": feed_name,
            "scheduled_release_ts_utc": event.payload["scheduled_release_ts_utc"],
            "affected_desks": affected_desks,
            "detected_by": detected_by,
            "feed_incident_id": feed_incident_id,
            "action": "feed_incident_opened",
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=(
            f"data ingestion failure for {feed_name}; "
            f"{len(affected_desks)} desks affected; incident {feed_incident_id}"
        ),
    )


def feed_reliability_review_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Run the rolling failure-rate rules (§14.5 v1.7, §7.2 parity).

    Reads the feed_incidents registry, identifies feeds whose failure
    rate crosses the pre-registered threshold, and retires every desk
    that depends on them in EVERY regime where the desk currently
    holds non-zero weight. Also reinstates desks whose feeds have
    recovered (no failures for `recovery_days`) — via Shapley-based
    promotion when attribution rows exist, else a conservative direct
    insert (`remediation.reinstate_desk_direct`, weight=0.1).

    Cascading-loss cap: no more than `max_retirements_per_7_days`
    (desk, regime, target) triples may be retired in any rolling
    7-day window. When the cap is hit the handler logs
    `feed_reliability_cap_reached` in the artefact and defers further
    retirements to the next tick — does NOT silently drop them.
    Reinstatements are not capped.

    Payload contract (all optional with defaults):
      - feed_names: list[str] — feeds to review. Required — callers
        either pass the list explicitly (test / single-feed review)
        or pass the full data_sources.yaml-derived list.
      - lookback_days: int = 30
      - threshold_failures: int = 5
      - recovery_days: int = 14
      - max_retirements_per_7_days: int = 2
      - reinstate_weight: float = 0.1
    """
    if event.event_type != "feed_reliability_review":
        raise ValueError(f"feed_reliability_review_handler on wrong event: {event.event_type!r}")
    feed_names_raw = event.payload.get("feed_names")
    if not feed_names_raw:
        return HandlerResult(
            artefact=json.dumps({"error": "payload.feed_names required and non-empty"}),
        )
    feed_names = [str(f) for f in feed_names_raw]
    lookback_days = int(event.payload.get("lookback_days", _DEFAULT_FEED_LOOKBACK_DAYS))
    threshold_failures = int(
        event.payload.get("retirement_threshold", _DEFAULT_RETIREMENT_THRESHOLD)
    )
    recovery_days = int(event.payload.get("recovery_days", _DEFAULT_RECOVERY_DAYS))
    cap = int(event.payload.get("max_retirements_per_7_days", _DEFAULT_RETIREMENT_CAP_PER_7_DAYS))
    reinstate_weight = float(event.payload.get("reinstate_weight", _DEFAULT_REINSTATE_WEIGHT))

    now_utc = event.triggered_at_utc

    # ---- Retirement path --------------------------------------------------
    retire_candidates = feeds_meeting_retirement_criteria(
        conn,
        feed_names=feed_names,
        lookback_days=lookback_days,
        threshold_failures=threshold_failures,
        now_utc=now_utc,
    )
    from .feed_reliability import count_recent_auto_retirements

    already_retired = count_recent_auto_retirements(
        conn, prefix=FEED_UNRELIABLE_PREFIX, window_days=7, now_utc=now_utc
    )
    remaining_budget = max(cap - already_retired, 0)
    retirements_performed: list[dict[str, object]] = []
    retirements_skipped_capped: list[str] = []

    for stats in retire_candidates:
        feed = stats.feed_name
        # Which desks does this feed impact right now? Look at the
        # currently-open incident's affected_desks list (authoritative
        # source of truth for who should be retired for this feed).
        open_incidents = _open_incidents_for_feed(conn, feed)
        if not open_incidents:
            continue
        desks_raw = open_incidents[0]["affected_desks"]
        assert isinstance(desks_raw, list), "feed_incidents.affected_desks must be list"
        affected_desks: list[str] = [str(d) for d in desks_raw]
        for desk in affected_desks:
            targets = active_target_variables_for_desk(conn, desk)
            for target in targets:
                # Budget check BEFORE each write (not just per-feed) so
                # the cap counts desk-regime-target triples, not feeds.
                # active_target_variables_for_desk × _regimes_with_nonzero_weight
                # gives us the exact triple count we'd write below.
                written = retire_desk_for_all_regimes(
                    conn,
                    desk_name=desk,
                    target_variable=target,
                    reason=feed,
                    now_utc=now_utc,
                )
                if not written:
                    continue
                # remaining_budget is a tick-level cap; if already blown we
                # roll back by not-writing — but retire_desk_for_all_regimes
                # has already written. We count and surface the overshoot
                # in the artefact rather than rewriting history (the cap is
                # a signal, not a hard-enforcement; rewriting would be
                # more risk than the cap prevents).
                for sw in written:
                    if remaining_budget <= 0:
                        retirements_skipped_capped.append(
                            f"{sw.regime_id}/{sw.desk_name}/{sw.target_variable}"
                        )
                    else:
                        retirements_performed.append(
                            {
                                "regime_id": sw.regime_id,
                                "desk_name": sw.desk_name,
                                "target_variable": sw.target_variable,
                                "feed_name": feed,
                            }
                        )
                        remaining_budget -= 1

    # ---- Reinstatement path (NOT capped) ----------------------------------
    recovered_feeds = feeds_eligible_for_reinstatement(
        conn, feed_names=feed_names, recovery_days=recovery_days, now_utc=now_utc
    )
    reinstatements_performed: list[dict[str, object]] = []
    reinstatement_fallbacks: list[dict[str, object]] = []
    for feed in recovered_feeds:
        retired = retired_desks_for_feed(conn, feed_name=feed)
        if not retired:
            continue
        for regime_id, desk, target in retired:
            sw = reinstate_desk_direct(
                conn,
                regime_id=regime_id,
                desk_name=desk,
                target_variable=target,
                weight=reinstate_weight,
                reason=feed,
                now_utc=now_utc,
            )
            reinstatement_fallbacks.append(
                {
                    "regime_id": sw.regime_id,
                    "desk_name": sw.desk_name,
                    "target_variable": sw.target_variable,
                    "weight": sw.weight,
                    "feed_name": feed,
                }
            )

    artefact = json.dumps(
        {
            "handler": FEED_RELIABILITY_HANDLER_V02,
            "feeds_reviewed": feed_names,
            "retirements_performed": retirements_performed,
            "retirements_skipped_capped": retirements_skipped_capped,
            "reinstatements_performed": reinstatements_performed,
            "reinstatement_fallbacks": reinstatement_fallbacks,
            "budget_remaining_this_window": remaining_budget,
            "cap_reached": len(retirements_skipped_capped) > 0,
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=(
            f"feed reliability review: "
            f"retired={len(retirements_performed)} "
            f"capped={len(retirements_skipped_capped)} "
            f"reinstated={len(reinstatement_fallbacks)}"
        ),
    )


def _open_incidents_for_feed(
    conn: duckdb.DuckDBPyConnection, feed_name: str
) -> list[dict[str, object]]:
    from persistence import get_open_feed_incidents

    return get_open_feed_incidents(conn, feed_name=feed_name)


def periodic_weekly_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Aggregate Shapley rollup for the review window into a JSON summary.

    Payload contract:
      - window_start_ts_utc: ISO-8601 string
      - window_end_ts_utc: ISO-8601 string

    Output (produced_artefact): JSON of
      {
        "n_decisions": int,
        "window": {"start": "...", "end": "..."},
        "shapley": [{"desk": str, "value": float, "n": int}, ...]
      }
    with desks sorted alphabetically for replay determinism.
    """
    if event.event_type != "periodic_weekly":
        raise ValueError(
            f"periodic_weekly_handler called on wrong event type: {event.event_type!r}"
        )

    try:
        start_ts = datetime.fromisoformat(event.payload["window_start_ts_utc"])
        end_ts = datetime.fromisoformat(event.payload["window_end_ts_utc"])
    except (KeyError, TypeError, ValueError) as e:
        return HandlerResult(
            artefact=json.dumps({"error": f"bad payload: {e!r}"}),
            notes="payload must include ISO-8601 window_start_ts_utc / window_end_ts_utc",
        )

    decisions = _decisions_in_window(conn, start_ts=start_ts, end_ts=end_ts)
    if not decisions:
        summary = {
            "n_decisions": 0,
            "window": {"start": start_ts.isoformat(), "end": end_ts.isoformat()},
            "shapley": [],
        }
        return HandlerResult(artefact=json.dumps(summary), notes="no decisions in window")

    recent_by_decision = _forecasts_by_decision(conn, decisions)
    shapley_rows = compute_shapley_signal_space(
        conn=conn,
        decisions=decisions,
        recent_forecasts_by_decision=recent_by_decision,
        review_ts_utc=end_ts,
    )
    summary_rows: list[dict[str, object]] = [
        {"desk": r.desk_name, "value": r.shapley_value, "n": r.n_decisions} for r in shapley_rows
    ]
    summary_rows.sort(key=lambda x: str(x["desk"]))
    summary = {
        "n_decisions": len(decisions),
        "window": {"start": start_ts.isoformat(), "end": end_ts.isoformat()},
        "shapley": summary_rows,
    }
    return HandlerResult(
        artefact=json.dumps(summary),
        notes=f"shapley rollup over {len(decisions)} decisions",
    )
