CREATE TABLE IF NOT EXISTS dim_date (
    date_id      SERIAL PRIMARY KEY,
    full_date    DATE        NOT NULL UNIQUE,
    year         SMALLINT    NOT NULL,
    month        SMALLINT    NOT NULL,
    day_of_month SMALLINT    NOT NULL,
    day_of_week  SMALLINT    NOT NULL,
    day_name     VARCHAR(10) NOT NULL,
    week_of_year SMALLINT    NOT NULL,
    is_weekend   BOOLEAN     NOT NULL,
    is_holiday   BOOLEAN     NOT NULL DEFAULT FALSE,
    holiday_name VARCHAR(100)
);
CREATE TABLE IF NOT EXISTS dim_route (
    route_key        SERIAL PRIMARY KEY,
    route_id         VARCHAR(20)  NOT NULL,
    route_short_name VARCHAR(50),
    route_long_name  VARCHAR(255),
    agency_id        VARCHAR(20),
    route_type       SMALLINT     DEFAULT 3,
    valid_from       DATE         NOT NULL DEFAULT CURRENT_DATE,
    valid_to         DATE         NOT NULL DEFAULT '2099-12-31',
    is_current       BOOLEAN      NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_dim_route_id
    ON dim_route (route_id) WHERE is_current = TRUE;
CREATE TABLE IF NOT EXISTS dim_stop (
    stop_key  SERIAL PRIMARY KEY,
    stop_id   VARCHAR(30) NOT NULL UNIQUE,
    stop_name VARCHAR(200),
    lat       DOUBLE PRECISION,
    lon       DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_dim_stop_id ON dim_stop (stop_id);
CREATE TABLE IF NOT EXISTS fact_trip_schedule (
    id               BIGSERIAL PRIMARY KEY,
    trip_id          VARCHAR(50)  NOT NULL,
    route_key        INT          REFERENCES dim_route(route_key),
    date_id          INT          REFERENCES dim_date(date_id),
    stop_sequence    SMALLINT     NOT NULL,
    stop_key         INT          REFERENCES dim_stop(stop_key),
    arrival_time     TIME,
    departure_time   TIME,
    arrival_day_off  SMALLINT     DEFAULT 0,
    loaded_at        TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_fts_trip_id   ON fact_trip_schedule (trip_id);
CREATE INDEX IF NOT EXISTS idx_fts_route_date ON fact_trip_schedule (route_key, date_id);
CREATE INDEX IF NOT EXISTS idx_fts_stop_seq  ON fact_trip_schedule (trip_id, stop_sequence);
CREATE TABLE IF NOT EXISTS fact_trip_actual (
    id                BIGSERIAL PRIMARY KEY,
    trip_id           VARCHAR(50)      NOT NULL,
    vehicle_id        VARCHAR(30),
    route_key         INT              REFERENCES dim_route(route_key),
    date_id           INT              REFERENCES dim_date(date_id),
    actual_departure  TIME,
    sched_departure   TIME,
    delay_minutes     DOUBLE PRECISION,
    is_on_time        BOOLEAN,
    headway_min       DOUBLE PRECISION,
    is_bunched        BOOLEAN,
    avg_speed_kmph    DOUBLE PRECISION,
    ping_count        INT,
    confidence        VARCHAR(10)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_fta_trip_vehicle
    ON fact_trip_actual (trip_id, vehicle_id);
CREATE INDEX IF NOT EXISTS idx_fta_route_date ON fact_trip_actual (route_key, date_id);
CREATE INDEX IF NOT EXISTS idx_fta_date_id    ON fact_trip_actual (date_id);
CREATE TABLE IF NOT EXISTS fact_weather_daily (
    id               SERIAL PRIMARY KEY,
    date_id          INT UNIQUE REFERENCES dim_date(date_id),
    temp_max_c       DOUBLE PRECISION,
    temp_min_c       DOUBLE PRECISION,
    precipitation_mm DOUBLE PRECISION,
    wind_max_kmph    DOUBLE PRECISION,
    is_rainy         BOOLEAN GENERATED ALWAYS AS (precipitation_mm > 2.5) STORED
);
CREATE TABLE IF NOT EXISTS fact_complaints (
    id             SERIAL PRIMARY KEY,
    complaint_id   VARCHAR(40) UNIQUE NOT NULL,
    route_key      INT          REFERENCES dim_route(route_key),
    date_id        INT          REFERENCES dim_date(date_id),
    stop_id        VARCHAR(30),
    vehicle_id     VARCHAR(30),
    category       VARCHAR(50),
    complaint_text TEXT,
    submitted_at   TIMESTAMPTZ,
    is_simulated   BOOLEAN NOT NULL DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS idx_fc_route_date ON fact_complaints (route_key, date_id);
CREATE TABLE IF NOT EXISTS etl_run_log (
    id           SERIAL PRIMARY KEY,
    run_at       TIMESTAMPTZ DEFAULT NOW(),
    script_name  VARCHAR(100),
    target_date  DATE,
    rows_loaded  INT,
    rows_skipped INT,
    rows_quarantined INT,
    status       VARCHAR(20),
    message      TEXT
);
CREATE TABLE IF NOT EXISTS quarantine_log (
    id          SERIAL PRIMARY KEY,
    logged_at   TIMESTAMPTZ DEFAULT NOW(),
    source_file VARCHAR(200),
    vehicle_id  VARCHAR(30),
    reason      VARCHAR(50),
    lat         DOUBLE PRECISION,
    lon         DOUBLE PRECISION
);
