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
    ROUND(
        AVG(avg_delay_min) OVER (
            PARTITION BY route_key
            ORDER BY full_date
            RANGE BETWEEN INTERVAL '6 days' PRECEDING AND CURRENT ROW
        )::NUMERIC,
    2)                                                         AS rolling_7d_avg_delay,
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
    )                                                          AS delay_trend
FROM daily_route_otp
ORDER BY route_short_name, full_date;
