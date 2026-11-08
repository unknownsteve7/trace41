-- =============================================================================
-- sql/06_rolling_otp.sql
-- 7-day rolling OTP per route using RANGE BETWEEN window frame.
-- Demonstrates: RANGE vs ROWS difference, date arithmetic in frames.
-- =============================================================================

-- ── RANGE vs ROWS — Key conceptual difference ──────────────────────────────────
-- ROWS: physical row offset (always exact count)
-- RANGE: logical value range (all rows with ORDER BY value in [current-N, current])
-- For date-based rolling windows, RANGE is correct because
-- missing days should still count as part of the same interval.

-- ── 7-day rolling OTP using RANGE BETWEEN ─────────────────────────────────────
WITH daily_route_otp AS (
    SELECT
        fa.route_key,
        dr.route_short_name,
        dd.full_date,
        COUNT(*)                                               AS trips_total,
        COUNT(*) FILTER (WHERE fa.is_on_time = TRUE)           AS trips_on_time,
        ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)               AS avg_delay_min
    FROM fact_trip_actual fa
    JOIN dim_route dr ON dr.route_key = fa.route_key
    JOIN dim_date  dd ON dd.date_id   = fa.date_id
    GROUP BY fa.route_key, dr.route_short_name, dd.full_date
)
SELECT
    route_short_name,
    full_date,
    trips_total,
    trips_on_time,
    ROUND(100.0 * trips_on_time / NULLIF(trips_total, 0), 1)   AS daily_otp_pct,
    avg_delay_min,

    -- 7-day rolling OTP: RANGE frame over date values
    ROUND(
        100.0
        * SUM(trips_on_time) OVER (
            PARTITION BY route_key
            ORDER BY full_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
          )
        / NULLIF(
            SUM(trips_total) OVER (
                PARTITION BY route_key
                ORDER BY full_date
                RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
            ), 0
          ),
    1)                                                         AS rolling_7d_otp_pct,

    -- 7-day rolling avg delay
    ROUND(
        AVG(avg_delay_min) OVER (
            PARTITION BY route_key
            ORDER BY full_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )::NUMERIC,
    2)                                                         AS rolling_7d_avg_delay,

    -- Trend: is OTP improving or declining?
    AVG(avg_delay_min) OVER (
        PARTITION BY route_key
        ORDER BY full_date
        RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
    )
    -
    AVG(avg_delay_min) OVER (
        PARTITION BY route_key
        ORDER BY full_date
        RANGE BETWEEN INTERVAL '13 days' PRECEDING AND INTERVAL '7 days' PRECEDING
    )                                                          AS delay_trend  -- positive = getting worse

FROM daily_route_otp
ORDER BY route_short_name, full_date;
