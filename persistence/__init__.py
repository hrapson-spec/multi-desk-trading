"""DuckDB persistence layer (spec §3.2).

Single database file `data/duckdb/main.duckdb` with all v1 tables.
See `schema.sql` for the authoritative schema.
"""

from __future__ import annotations

from .db import (
    DEFAULT_DB_PATH,
    connect,
    count_rows,
    get_latest_controller_params,
    get_latest_signal_weights,
    init_db,
    insert_controller_params,
    insert_decision,
    insert_forecast,
    insert_grade,
    insert_print,
    insert_regime_label,
    insert_research_loop_event,
    insert_signal_weight,
    match_candidate_prints,
    replay_forecasts,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "connect",
    "count_rows",
    "get_latest_controller_params",
    "get_latest_signal_weights",
    "init_db",
    "insert_controller_params",
    "insert_decision",
    "insert_forecast",
    "insert_grade",
    "insert_print",
    "insert_regime_label",
    "insert_research_loop_event",
    "insert_signal_weight",
    "match_candidate_prints",
    "replay_forecasts",
]
