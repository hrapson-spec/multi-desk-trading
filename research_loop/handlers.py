"""Concrete handlers bound to event types by the Dispatcher (spec §6.3).

v0.1 ships one handler:

  periodic_weekly_handler — pulls all Decisions in the review window
  from the event.payload (keys: `window_start_ts_utc`,
  `window_end_ts_utc`) and runs a compact Shapley rollup, storing a
  JSON summary (desk, shapley_value, n_decisions) in the event's
  produced_artefact. Gate-failure, regime-transition, and data-
  ingestion-failure handlers follow in later commits.

Design guardrail: handlers are pure w.r.t. their inputs except for
explicit DB writes (new AttributionShapley rows). No filesystem
writes, no network, no LLM calls in v0.1 — those live in later
layers per §6.4 routing discipline.
"""

from __future__ import annotations

import json
from datetime import datetime

import duckdb

from attribution import compute_shapley_signal_space
from contracts.v1 import Decision, Forecast, Provenance, ResearchLoopEvent

from .dispatcher import HandlerResult


def _decisions_in_window(
    conn: duckdb.DuckDBPyConnection,
    *,
    start_ts: datetime,
    end_ts: datetime,
) -> list[Decision]:
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
    """Record a structured gate-failure artefact (§6.2, §7.2 harmful-case
    feeder). v0.1 logs; remediation proposals (desk retire, re-train,
    escalate) are §7.3 escalation-ladder handlers in later commits.

    Payload contract (pre-registered):
      - desk: str (desk_name)
      - gate: str — "skill" | "sign_preservation" | "hot_swap"
      - metric: float — gate's pass/fail margin
      - failure_mode: str — short human-readable tag
    """
    if event.event_type != "gate_failure":
        raise ValueError(f"gate_failure_handler on wrong event: {event.event_type!r}")
    _ = conn
    required = {"desk", "gate", "metric", "failure_mode"}
    missing = required - set(event.payload.keys())
    if missing:
        return HandlerResult(
            artefact=json.dumps({"error": f"missing payload keys: {sorted(missing)}"}),
        )
    artefact = json.dumps(
        {
            "handler": "gate_failure_v0.1",
            "desk": event.payload["desk"],
            "gate": event.payload["gate"],
            "metric": event.payload["metric"],
            "failure_mode": event.payload["failure_mode"],
            "action": "logged_pending_rca",
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=f"gate_failure logged for {event.payload['desk']}/{event.payload['gate']}",
    )


def regime_transition_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Log a regime transition (§6.2) — proposing a weight-promotion
    refresh is v0.2 work. Payload contract:

      - from_regime: str
      - to_regime: str
      - probability: float (>= 0.7 per §6.2 default threshold)
    """
    if event.event_type != "regime_transition":
        raise ValueError(f"regime_transition_handler on wrong event: {event.event_type!r}")
    _ = conn
    required = {"from_regime", "to_regime", "probability"}
    missing = required - set(event.payload.keys())
    if missing:
        return HandlerResult(
            artefact=json.dumps({"error": f"missing payload keys: {sorted(missing)}"}),
        )
    artefact = json.dumps(
        {
            "handler": "regime_transition_v0.1",
            "from": event.payload["from_regime"],
            "to": event.payload["to_regime"],
            "probability": event.payload["probability"],
            "action": "logged_no_weight_refresh",  # v0.2 will trigger refresh
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=(f"regime transition {event.payload['from_regime']} → {event.payload['to_regime']}"),
    )


def data_ingestion_failure_handler(
    conn: duckdb.DuckDBPyConnection, event: ResearchLoopEvent
) -> HandlerResult:
    """Log a data-ingestion failure (§6.2, §14.5 data-quality invariant).
    Remediation (mark affected desks stale, switch to fallback feed) is
    v0.2 work. Payload contract:

      - feed: str (name of the feed)
      - scheduled_release_ts_utc: ISO-8601 string
      - affected_desks: list[str]
    """
    if event.event_type != "data_ingestion_failure":
        raise ValueError(f"data_ingestion_failure_handler on wrong event: {event.event_type!r}")
    _ = conn
    required = {"feed", "scheduled_release_ts_utc", "affected_desks"}
    missing = required - set(event.payload.keys())
    if missing:
        return HandlerResult(
            artefact=json.dumps({"error": f"missing payload keys: {sorted(missing)}"}),
        )
    artefact = json.dumps(
        {
            "handler": "data_ingestion_failure_v0.1",
            "feed": event.payload["feed"],
            "scheduled_release_ts_utc": event.payload["scheduled_release_ts_utc"],
            "affected_desks": event.payload["affected_desks"],
            "action": "logged_pending_fallback_check",
        }
    )
    return HandlerResult(
        artefact=artefact,
        notes=(
            f"data ingestion failure for {event.payload['feed']}; "
            f"{len(event.payload['affected_desks'])} desks affected"
        ),
    )


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
