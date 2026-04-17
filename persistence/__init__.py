"""DuckDB persistence layer (spec §3.2).

Single database file `data/duckdb/main.duckdb` with all v1 tables.
See `schema.sql` for the authoritative schema.
"""

from __future__ import annotations

from .db import (
    DEFAULT_DB_PATH,
    close_feed_incident,
    connect,
    count_feed_incidents_in_window,
    count_rows,
    get_feed_latency_state,
    get_latest_controller_params,
    get_latest_regime_label,
    get_latest_signal_weights,
    get_open_feed_incidents,
    init_db,
    insert_attribution_lodo,
    insert_attribution_shapley,
    insert_controller_params,
    insert_decision,
    insert_forecast,
    insert_grade,
    insert_print,
    insert_regime_label,
    insert_research_loop_event,
    insert_signal_weight,
    insert_soak_incident,
    insert_soak_resource_sample,
    match_candidate_prints,
    open_feed_incident,
    replay_forecasts,
    upsert_feed_latency_state,
)

__all__ = [
    "DEFAULT_DB_PATH",
    "close_feed_incident",
    "connect",
    "count_feed_incidents_in_window",
    "count_rows",
    "get_feed_latency_state",
    "get_latest_controller_params",
    "get_latest_regime_label",
    "get_latest_signal_weights",
    "get_open_feed_incidents",
    "init_db",
    "insert_attribution_lodo",
    "insert_attribution_shapley",
    "insert_controller_params",
    "insert_decision",
    "insert_forecast",
    "insert_grade",
    "insert_print",
    "insert_regime_label",
    "insert_research_loop_event",
    "insert_signal_weight",
    "insert_soak_incident",
    "insert_soak_resource_sample",
    "match_candidate_prints",
    "open_feed_incident",
    "replay_forecasts",
    "upsert_feed_latency_state",
]
