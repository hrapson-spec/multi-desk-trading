-- DuckDB schema for the multi-desk trading architecture (v1 API).
-- Single database file: data/duckdb/main.duckdb (spec §3.2).
-- Every CREATE is IF NOT EXISTS so init_db() is idempotent.

-- ---------------------------------------------------------------------------
-- forecasts: immutable emissions from desks (spec §4.3 Forecast)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id        VARCHAR PRIMARY KEY,
    emission_ts_utc    TIMESTAMPTZ NOT NULL,
    desk_name          VARCHAR NOT NULL,
    target_variable    VARCHAR NOT NULL,
    horizon_kind       VARCHAR NOT NULL CHECK (horizon_kind IN ('clock', 'event')),
    horizon_payload    JSON NOT NULL,
    point_estimate     DOUBLE NOT NULL,
    uncertainty        JSON NOT NULL,
    directional_claim  JSON NOT NULL,
    staleness          BOOLEAN NOT NULL DEFAULT FALSE,
    confidence         DOUBLE NOT NULL DEFAULT 1.0,
    provenance         JSON NOT NULL,
    supersedes         VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_forecasts_emission
    ON forecasts (desk_name, emission_ts_utc, target_variable);

-- ---------------------------------------------------------------------------
-- prints: realised outcomes (spec §4.3 Print)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS prints (
    print_id          VARCHAR PRIMARY KEY,
    realised_ts_utc   TIMESTAMPTZ NOT NULL,
    target_variable   VARCHAR NOT NULL,
    value             DOUBLE NOT NULL,
    event_id          VARCHAR,
    vintage_of        VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_prints_target
    ON prints (target_variable, realised_ts_utc);
CREATE INDEX IF NOT EXISTS idx_prints_event
    ON prints (event_id);

-- ---------------------------------------------------------------------------
-- grades: Forecast × Print match outputs (spec §4.3 Grade, §4.7 matching)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grades (
    grade_id               VARCHAR PRIMARY KEY,
    forecast_id            VARCHAR NOT NULL,
    print_id               VARCHAR NOT NULL,
    grading_ts_utc         TIMESTAMPTZ NOT NULL,
    squared_error          DOUBLE NOT NULL,
    absolute_error         DOUBLE NOT NULL,
    log_score              DOUBLE,
    sign_agreement         BOOLEAN,
    within_uncertainty     BOOLEAN,
    schedule_slip_seconds  DOUBLE
);
CREATE INDEX IF NOT EXISTS idx_grades_forecast ON grades (forecast_id);

-- ---------------------------------------------------------------------------
-- decisions: immutable Controller decisions (spec §3.1 new invariant, §3.2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS decisions (
    decision_id         VARCHAR PRIMARY KEY,
    emission_ts_utc     TIMESTAMPTZ NOT NULL,
    regime_id           VARCHAR NOT NULL,
    combined_signal     DOUBLE NOT NULL,
    position_size       DOUBLE NOT NULL,
    input_forecast_ids  JSON NOT NULL,
    provenance          JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_ts ON decisions (emission_ts_utc, regime_id);

-- ---------------------------------------------------------------------------
-- signal_weights: regime-conditional weight matrix rows (spec §4.3, §8.3)
-- Tuple (regime_id, desk_name, target_variable, promotion_ts_utc) is a
-- non-unique index; Controller reads break ties on same promotion_ts_utc by
-- lexicographic weight_id.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS signal_weights (
    weight_id            VARCHAR PRIMARY KEY,
    regime_id            VARCHAR NOT NULL,
    desk_name            VARCHAR NOT NULL,
    target_variable      VARCHAR NOT NULL,
    weight               DOUBLE NOT NULL,
    promotion_ts_utc     TIMESTAMPTZ NOT NULL,
    validation_artefact  VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signal_weights_lookup
    ON signal_weights (regime_id, desk_name, target_variable, promotion_ts_utc);

-- ---------------------------------------------------------------------------
-- controller_params: per-regime k_regime and pos_limit_regime
-- (spec §3.2 v1.3, §4.3 ControllerParams, §8.2a linear sizing function)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS controller_params (
    params_id            VARCHAR PRIMARY KEY,
    regime_id            VARCHAR NOT NULL,
    k_regime             DOUBLE NOT NULL,
    pos_limit_regime     DOUBLE NOT NULL CHECK (pos_limit_regime >= 0),
    promotion_ts_utc     TIMESTAMPTZ NOT NULL,
    validation_artefact  VARCHAR NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_controller_params_lookup
    ON controller_params (regime_id, promotion_ts_utc);

-- ---------------------------------------------------------------------------
-- attribution_lodo: leave-one-desk-out per decision per desk (spec §9.1)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attribution_lodo (
    attribution_id       VARCHAR PRIMARY KEY,
    decision_id          VARCHAR NOT NULL,
    desk_name            VARCHAR NOT NULL,
    contribution_metric  DOUBLE NOT NULL,
    metric_name          VARCHAR NOT NULL,
    computed_ts_utc      TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attribution_lodo_decision
    ON attribution_lodo (decision_id, desk_name);

-- ---------------------------------------------------------------------------
-- attribution_shapley: weekly Shapley credit scores (spec §9.2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS attribution_shapley (
    attribution_id   VARCHAR PRIMARY KEY,
    review_ts_utc    TIMESTAMPTZ NOT NULL,
    desk_name        VARCHAR NOT NULL,
    shapley_value    DOUBLE NOT NULL,
    metric_name      VARCHAR NOT NULL,
    n_decisions      INTEGER NOT NULL,
    coalitions_mode  VARCHAR NOT NULL CHECK (coalitions_mode IN ('exact', 'sampled'))
);
CREATE INDEX IF NOT EXISTS idx_attribution_shapley_review
    ON attribution_shapley (review_ts_utc, desk_name);

-- ---------------------------------------------------------------------------
-- research_loop_events: triggers and periodic reviews (spec §4.3, §6.2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_loop_events (
    event_id            VARCHAR PRIMARY KEY,
    event_type          VARCHAR NOT NULL,
    triggered_at_utc    TIMESTAMPTZ NOT NULL,
    priority            INTEGER NOT NULL,
    payload             JSON NOT NULL,
    completed_at_utc    TIMESTAMPTZ,
    produced_artefact   VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_research_loop_events_type
    ON research_loop_events (event_type, triggered_at_utc);

-- ---------------------------------------------------------------------------
-- model_registry: deployed model versions (spec §3.2)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS model_registry (
    registry_id            VARCHAR PRIMARY KEY,
    desk_name              VARCHAR NOT NULL,
    model_name             VARCHAR NOT NULL,
    version                VARCHAR NOT NULL,
    registration_ts_utc    TIMESTAMPTZ NOT NULL,
    artefact_path          VARCHAR,
    config_hash            VARCHAR,
    data_snapshot_hash     VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_model_registry_desk
    ON model_registry (desk_name, model_name, version);

-- ---------------------------------------------------------------------------
-- regime_labels: classifier outputs (spec §4.3 RegimeLabel, §10)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS regime_labels (
    label_id                  VARCHAR PRIMARY KEY,
    classification_ts_utc     TIMESTAMPTZ NOT NULL,
    regime_id                 VARCHAR NOT NULL,
    regime_probabilities      JSON NOT NULL,
    transition_probabilities  JSON NOT NULL,
    classifier_provenance     JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_regime_labels_ts
    ON regime_labels (classification_ts_utc);

-- ---------------------------------------------------------------------------
-- soak_resource_samples: wall-clock Reliability-gate resource telemetry
-- (spec §12.2 point 3, §14.9 v1.6). Written by soak/monitor.py.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS soak_resource_samples (
    sample_id       VARCHAR PRIMARY KEY,
    ts_utc          TIMESTAMPTZ NOT NULL,
    elapsed_seconds DOUBLE NOT NULL,
    rss_bytes       BIGINT NOT NULL,
    open_fds        INTEGER NOT NULL,
    db_size_bytes   BIGINT NOT NULL,
    n_decisions     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_soak_resource_samples_ts
    ON soak_resource_samples (ts_utc);

-- ---------------------------------------------------------------------------
-- soak_incidents: numeric-thresholded infrastructure incidents during the
-- Reliability gate run. Gate failures are NOT incidents (§12.2 rule).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS soak_incidents (
    incident_id     VARCHAR PRIMARY KEY,
    detected_ts_utc TIMESTAMPTZ NOT NULL,
    incident_class  VARCHAR NOT NULL,
    detail          JSON NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_soak_incidents_ts
    ON soak_incidents (detected_ts_utc);

-- ---------------------------------------------------------------------------
-- feed_incidents: open/closed incidents for upstream data-feed outages
-- (spec §14.5 staleness-propagation invariant, §7.2 feed-unreliable retire).
-- closed_ts_utc IS NULL ⇒ open. Index is the hot-path query for the
-- desk-side _staleness_from_feeds check.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feed_incidents (
    feed_incident_id     VARCHAR PRIMARY KEY,
    feed_name            VARCHAR NOT NULL,
    opened_ts_utc        TIMESTAMPTZ NOT NULL,
    closed_ts_utc        TIMESTAMPTZ,
    affected_desks       JSON NOT NULL,
    detected_by          VARCHAR NOT NULL
        CHECK (detected_by IN ('scheduler', 'page_hinkley', 'manual')),
    resolution_artefact  VARCHAR,
    opening_event_id     VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_feed_incidents_open
    ON feed_incidents (feed_name, closed_ts_utc);

-- ---------------------------------------------------------------------------
-- feed_latency_state: per-feed Page-Hinkley detector state persisted across
-- process restarts (§14.5 v1.7). Upsert on every scheduler firing; tripped
-- carries forward until a feed_incidents close resets it to FALSE.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS feed_latency_state (
    feed_name             VARCHAR PRIMARY KEY,
    cumulative_sum        DOUBLE NOT NULL,
    min_cumulative        DOUBLE NOT NULL,
    n_observations        BIGINT NOT NULL,
    last_update_ts_utc    TIMESTAMPTZ,
    tripped               BOOLEAN NOT NULL
);
