"""DuckDB persistence layer.

Single database file at data/duckdb/main.duckdb (spec §3.2).
Idempotent schema init; typed insert + query helpers for each event table.

Point-in-time correctness: queries that accept as_of_ts return only rows
whose emission_ts_utc (or equivalent) is ≤ as_of_ts. This is how replay
reconstructs "what did the desk see at date X".
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from contracts.v1 import (
    AttributionLodo,
    AttributionShapley,
    ControllerParams,
    Decision,
    Forecast,
    Grade,
    Print,
    RegimeLabel,
    ResearchLoopEvent,
    SignalWeight,
)

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

DEFAULT_DB_PATH = Path("data/duckdb/main.duckdb")


# ---------------------------------------------------------------------------
# Connection / init
# ---------------------------------------------------------------------------


def connect(path: Path | None = None) -> duckdb.DuckDBPyConnection:
    target = Path(path) if path is not None else DEFAULT_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(target))


def init_db(conn: duckdb.DuckDBPyConnection) -> None:
    """Run schema.sql idempotently."""
    sql = _SCHEMA_PATH.read_text()
    # DuckDB's .execute() handles multi-statement input via .executescript-equivalent.
    conn.execute(sql)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _json_default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, timedelta):
        # Serialise as seconds (float); Pydantic v2 coerces int/float → timedelta.
        return obj.total_seconds()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def _dumps(obj: Any) -> str:
    """Canonical JSON serialisation for inlined sub-objects.

    Sorted keys + default handler for datetimes and Pydantic models.
    """
    return json.dumps(obj, default=_json_default, sort_keys=True)


# ---------------------------------------------------------------------------
# Inserts
# ---------------------------------------------------------------------------


def insert_forecast(conn: duckdb.DuckDBPyConnection, f: Forecast) -> None:
    horizon_payload = f.horizon.model_dump()
    conn.execute(
        """
        INSERT INTO forecasts (
            forecast_id, emission_ts_utc, desk_name, target_variable,
            horizon_kind, horizon_payload, point_estimate, uncertainty,
            directional_claim, staleness, confidence, provenance, supersedes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            f.forecast_id,
            f.emission_ts_utc,
            f.provenance.desk_name,
            f.target_variable,
            f.horizon.kind,
            _dumps(horizon_payload),
            f.point_estimate,
            _dumps(f.uncertainty.model_dump()),
            _dumps(f.directional_claim.model_dump()),
            f.staleness,
            f.confidence,
            _dumps(f.provenance.model_dump()),
            f.supersedes,
        ],
    )


def insert_print(conn: duckdb.DuckDBPyConnection, p: Print) -> None:
    conn.execute(
        """
        INSERT INTO prints (
            print_id, realised_ts_utc, target_variable, value, event_id, vintage_of
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [p.print_id, p.realised_ts_utc, p.target_variable, p.value, p.event_id, p.vintage_of],
    )


def insert_grade(conn: duckdb.DuckDBPyConnection, g: Grade) -> None:
    conn.execute(
        """
        INSERT INTO grades (
            grade_id, forecast_id, print_id, grading_ts_utc,
            squared_error, absolute_error, log_score,
            sign_agreement, within_uncertainty, schedule_slip_seconds
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            g.grade_id,
            g.forecast_id,
            g.print_id,
            g.grading_ts_utc,
            g.squared_error,
            g.absolute_error,
            g.log_score,
            g.sign_agreement,
            g.within_uncertainty,
            g.schedule_slip_seconds,
        ],
    )


def insert_decision(conn: duckdb.DuckDBPyConnection, d: Decision) -> None:
    conn.execute(
        """
        INSERT INTO decisions (
            decision_id, emission_ts_utc, regime_id, combined_signal,
            position_size, input_forecast_ids, provenance
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            d.decision_id,
            d.emission_ts_utc,
            d.regime_id,
            d.combined_signal,
            d.position_size,
            _dumps(d.input_forecast_ids),
            _dumps(d.provenance.model_dump()),
        ],
    )


def insert_signal_weight(conn: duckdb.DuckDBPyConnection, w: SignalWeight) -> None:
    conn.execute(
        """
        INSERT INTO signal_weights (
            weight_id, regime_id, desk_name, target_variable,
            weight, promotion_ts_utc, validation_artefact
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            w.weight_id,
            w.regime_id,
            w.desk_name,
            w.target_variable,
            w.weight,
            w.promotion_ts_utc,
            w.validation_artefact,
        ],
    )


def insert_controller_params(conn: duckdb.DuckDBPyConnection, cp: ControllerParams) -> None:
    conn.execute(
        """
        INSERT INTO controller_params (
            params_id, regime_id, k_regime, pos_limit_regime,
            promotion_ts_utc, validation_artefact
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            cp.params_id,
            cp.regime_id,
            cp.k_regime,
            cp.pos_limit_regime,
            cp.promotion_ts_utc,
            cp.validation_artefact,
        ],
    )


def insert_regime_label(conn: duckdb.DuckDBPyConnection, r: RegimeLabel) -> None:
    conn.execute(
        """
        INSERT INTO regime_labels (
            label_id, classification_ts_utc, regime_id,
            regime_probabilities, transition_probabilities, classifier_provenance
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            str(uuid.uuid4()),
            r.classification_ts_utc,
            r.regime_id,
            _dumps(r.regime_probabilities),
            _dumps(r.transition_probabilities),
            _dumps(r.classifier_provenance.model_dump()),
        ],
    )


def insert_attribution_lodo(conn: duckdb.DuckDBPyConnection, a: AttributionLodo) -> None:
    conn.execute(
        """
        INSERT INTO attribution_lodo (
            attribution_id, decision_id, desk_name,
            contribution_metric, metric_name, computed_ts_utc
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            a.attribution_id,
            a.decision_id,
            a.desk_name,
            a.contribution_metric,
            a.metric_name,
            a.computed_ts_utc,
        ],
    )


def insert_attribution_shapley(conn: duckdb.DuckDBPyConnection, a: AttributionShapley) -> None:
    conn.execute(
        """
        INSERT INTO attribution_shapley (
            attribution_id, review_ts_utc, desk_name,
            shapley_value, metric_name, n_decisions, coalitions_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            a.attribution_id,
            a.review_ts_utc,
            a.desk_name,
            a.shapley_value,
            a.metric_name,
            a.n_decisions,
            a.coalitions_mode,
        ],
    )


def insert_research_loop_event(conn: duckdb.DuckDBPyConnection, e: ResearchLoopEvent) -> None:
    conn.execute(
        """
        INSERT INTO research_loop_events (
            event_id, event_type, triggered_at_utc,
            priority, payload, completed_at_utc, produced_artefact
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            e.event_id,
            e.event_type,
            e.triggered_at_utc,
            e.priority,
            _dumps(e.payload),
            e.completed_at_utc,
            e.produced_artefact,
        ],
    )


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


def replay_forecasts(
    conn: duckdb.DuckDBPyConnection,
    start_ts_utc: datetime,
    end_ts_utc: datetime,
) -> Iterable[dict[str, Any]]:
    """Iterate forecasts in emission order within a window."""
    for row in conn.execute(
        """
        SELECT forecast_id, emission_ts_utc, desk_name, target_variable,
               horizon_kind, horizon_payload, point_estimate, uncertainty,
               directional_claim, staleness, confidence, provenance, supersedes
        FROM forecasts
        WHERE emission_ts_utc >= ? AND emission_ts_utc <= ?
        ORDER BY emission_ts_utc, forecast_id
        """,
        [start_ts_utc, end_ts_utc],
    ).fetchall():
        yield {
            "forecast_id": row[0],
            "emission_ts_utc": row[1],
            "desk_name": row[2],
            "target_variable": row[3],
            "horizon_kind": row[4],
            "horizon_payload": json.loads(row[5]),
            "point_estimate": row[6],
            "uncertainty": json.loads(row[7]),
            "directional_claim": json.loads(row[8]),
            "staleness": row[9],
            "confidence": row[10],
            "provenance": json.loads(row[11]),
            "supersedes": row[12],
        }


def get_latest_signal_weights(
    conn: duckdb.DuckDBPyConnection, regime_id: str
) -> list[dict[str, Any]]:
    """Latest weight per (desk, target) for the given regime.

    Ties on promotion_ts_utc broken by lexicographic weight_id (spec §8.3).
    """
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT
                desk_name, target_variable, weight, weight_id,
                promotion_ts_utc, validation_artefact,
                ROW_NUMBER() OVER (
                    PARTITION BY desk_name, target_variable
                    ORDER BY promotion_ts_utc DESC, weight_id DESC
                ) AS rn
            FROM signal_weights
            WHERE regime_id = ?
        )
        SELECT desk_name, target_variable, weight, weight_id,
               promotion_ts_utc, validation_artefact
        FROM ranked
        WHERE rn = 1
        ORDER BY desk_name, target_variable
        """,
        [regime_id],
    ).fetchall()
    return [
        {
            "desk_name": r[0],
            "target_variable": r[1],
            "weight": r[2],
            "weight_id": r[3],
            "promotion_ts_utc": r[4],
            "validation_artefact": r[5],
        }
        for r in rows
    ]


def get_latest_regime_label(
    conn: duckdb.DuckDBPyConnection, as_of_ts: datetime | None = None
) -> dict[str, Any] | None:
    """Most recent RegimeLabel at or before as_of_ts (None → no bound).

    Returns a dict with the hydrated probability/transition maps, or None
    if no RegimeLabel row exists in the bounded window.
    """
    if as_of_ts is None:
        row = conn.execute(
            """
            SELECT label_id, classification_ts_utc, regime_id,
                   regime_probabilities, transition_probabilities, classifier_provenance
            FROM regime_labels
            ORDER BY classification_ts_utc DESC, label_id DESC
            LIMIT 1
            """,
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT label_id, classification_ts_utc, regime_id,
                   regime_probabilities, transition_probabilities, classifier_provenance
            FROM regime_labels
            WHERE classification_ts_utc <= ?
            ORDER BY classification_ts_utc DESC, label_id DESC
            LIMIT 1
            """,
            [as_of_ts],
        ).fetchone()
    if row is None:
        return None
    return {
        "label_id": row[0],
        "classification_ts_utc": row[1],
        "regime_id": row[2],
        "regime_probabilities": json.loads(row[3]),
        "transition_probabilities": json.loads(row[4]),
        "classifier_provenance": json.loads(row[5]),
    }


def get_latest_controller_params(
    conn: duckdb.DuckDBPyConnection, regime_id: str
) -> dict[str, Any] | None:
    """Latest ControllerParams for the given regime; None if no row exists.

    Ties on promotion_ts_utc broken by lexicographic params_id (spec §8.3).
    """
    row = conn.execute(
        """
        SELECT params_id, regime_id, k_regime, pos_limit_regime,
               promotion_ts_utc, validation_artefact
        FROM controller_params
        WHERE regime_id = ?
        ORDER BY promotion_ts_utc DESC, params_id DESC
        LIMIT 1
        """,
        [regime_id],
    ).fetchone()
    if row is None:
        return None
    return {
        "params_id": row[0],
        "regime_id": row[1],
        "k_regime": row[2],
        "pos_limit_regime": row[3],
        "promotion_ts_utc": row[4],
        "validation_artefact": row[5],
    }


def match_candidate_prints(
    conn: duckdb.DuckDBPyConnection,
    target_variable: str,
    event_id: str | None,
) -> list[dict[str, Any]]:
    """Candidate Prints for Forecast→Print matching (§4.7).

    For EventHorizon forecasts pass event_id; for ClockHorizon pass None
    and filter by time window at the caller.
    """
    if event_id is not None:
        rows = conn.execute(
            """
            SELECT print_id, realised_ts_utc, target_variable, value, event_id, vintage_of
            FROM prints
            WHERE target_variable = ? AND event_id = ?
            ORDER BY realised_ts_utc
            """,
            [target_variable, event_id],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT print_id, realised_ts_utc, target_variable, value, event_id, vintage_of
            FROM prints
            WHERE target_variable = ?
            ORDER BY realised_ts_utc
            """,
            [target_variable],
        ).fetchall()
    return [
        {
            "print_id": r[0],
            "realised_ts_utc": r[1],
            "target_variable": r[2],
            "value": r[3],
            "event_id": r[4],
            "vintage_of": r[5],
        }
        for r in rows
    ]


def count_rows(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    """Utility for tests."""
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # type: ignore[index,no-any-return]
