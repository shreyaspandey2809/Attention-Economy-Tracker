-- M8 initial schema. Timestamps are UTC ISO-8601 text ("YYYY-MM-DDTHH:MM:SS.ffffffZ");
-- `day` columns are local calendar dates ("YYYY-MM-DD"), matching pipeline/windowing.py.

CREATE TABLE users (
    user_id          TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL,
    consent_at       TEXT,
    -- 1 when raw_events changed since the last scoring run; cleared by the scoring job.
    scores_stale     INTEGER NOT NULL DEFAULT 1,
    last_scored_at   TEXT
);

CREATE TABLE devices (
    device_id    TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    token_hash   TEXT NOT NULL UNIQUE,
    created_at   TEXT NOT NULL,
    revoked_at   TEXT
);
CREATE INDEX idx_devices_user ON devices(user_id);

CREATE TABLE app_metadata (
    package_name      TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,
    category          TEXT NOT NULL,
    is_user_override  INTEGER NOT NULL DEFAULT 0
);

-- Source of truth. Everything below this table is derived and can be rebuilt.
CREATE TABLE raw_events (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id               TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    package_name          TEXT NOT NULL,
    event_type            TEXT NOT NULL,
    timestamp             TEXT NOT NULL,
    tz_offset_minutes     INTEGER NOT NULL,
    session_duration_sec  REAL,
    session_id            TEXT,
    -- Idempotency: a re-sent batch inserts nothing.
    UNIQUE (user_id, package_name, event_type, timestamp)
);
CREATE INDEX idx_raw_events_user_ts ON raw_events(user_id, timestamp);

CREATE TABLE sessions (
    user_id           TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    session_id        TEXT NOT NULL,
    package_name      TEXT NOT NULL,
    start_time        TEXT NOT NULL,
    end_time          TEXT NOT NULL,
    duration_sec      REAL NOT NULL,
    tz_offset_minutes INTEGER NOT NULL,
    transition_from   TEXT,
    transition_to     TEXT,
    PRIMARY KEY (user_id, session_id)
);
CREATE INDEX idx_sessions_user_start ON sessions(user_id, start_time);

-- One row per (user, app, local day) window. NULL = undefined feature (never 0).
CREATE TABLE feature_vectors (
    user_id                        TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    package_name                   TEXT NOT NULL,
    day                            TEXT NOT NULL,
    category                       TEXT NOT NULL,
    total_time_sec                 REAL NOT NULL,
    session_count                  INTEGER NOT NULL,
    avg_session_duration_sec       REAL NOT NULL,
    max_session_duration_sec       REAL NOT NULL,
    sessions_under_30s_ratio       REAL NOT NULL,
    interarrival_mean_sec          REAL,
    interarrival_under_2min_ratio  REAL,
    late_night_usage_pct           REAL NOT NULL,
    late_night_usage_time_ratio    REAL NOT NULL,
    hourly_usage_entropy           REAL NOT NULL,
    weekend_usage_ratio            REAL NOT NULL,
    productive_interruption_rate   REAL NOT NULL,
    PRIMARY KEY (user_id, package_name, day)
);

-- Scores for one window. Model columns are NULL when no trained model existed at scoring time.
CREATE TABLE scores (
    user_id                    TEXT NOT NULL,
    package_name               TEXT NOT NULL,
    day                        TEXT NOT NULL,
    heuristic_score            REAL NOT NULL,
    distraction_score          REAL NOT NULL,
    addiction_model_score      REAL,
    distraction_model_score    REAL,
    addiction_model_version    TEXT,
    distraction_model_version  TEXT,
    scored_at                  TEXT NOT NULL,
    PRIMARY KEY (user_id, package_name, day),
    FOREIGN KEY (user_id, package_name, day)
        REFERENCES feature_vectors(user_id, package_name, day) ON DELETE CASCADE
);

-- Per-day roll-up: time-weighted mean of the per-app scores + completeness flag.
CREATE TABLE daily_scores (
    user_id                  TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    day                      TEXT NOT NULL,
    total_time_sec           REAL NOT NULL,
    heuristic_score          REAL NOT NULL,
    distraction_score        REAL NOT NULL,
    addiction_model_score    REAL,
    distraction_model_score  REAL,
    is_complete              INTEGER NOT NULL,
    max_gap_hours            REAL NOT NULL,
    completeness_reason      TEXT NOT NULL,
    PRIMARY KEY (user_id, day)
);

-- Only the SAS-SV total is stored. Item wording / per-item answers are deliberately not kept.
CREATE TABLE sas_sv_labels (
    user_id        TEXT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    sas_sv_total   INTEGER NOT NULL CHECK (sas_sv_total BETWEEN 10 AND 60),
    collected_at   TEXT NOT NULL
);
