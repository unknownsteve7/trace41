CREATE OR REPLACE VIEW v_route_daily_kpis AS
SELECT
    dd.full_date,
    dd.day_name,
    dd.is_weekend,
    dd.is_holiday,
    dr.route_id,
    dr.route_short_name,
    dr.route_long_name,
    COUNT(fa.id)                                              AS trips_observed,
    COUNT(*) FILTER (WHERE fa.is_on_time = TRUE)              AS trips_on_time,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fa.is_on_time = TRUE)
              / NULLIF(COUNT(fa.id), 0),
    1)                                                        AS otp_pct,
    ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)                  AS avg_delay_min,
    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP
          (ORDER BY fa.delay_minutes)::NUMERIC, 2)            AS median_delay_min,
    COUNT(*) FILTER (WHERE fa.is_bunched = TRUE)              AS bunched_trips,
    ROUND(AVG(fa.headway_min)::NUMERIC, 2)                    AS avg_headway_min,
    ROUND(AVG(fa.avg_speed_kmph)::NUMERIC, 2)                 AS avg_speed_kmph
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
JOIN dim_date  dd ON dd.date_id   = fa.date_id
GROUP BY dd.full_date, dd.day_name, dd.is_weekend, dd.is_holiday,
         dr.route_id, dr.route_short_name, dr.route_long_name;
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_hourly_headway AS
SELECT
    dr.route_short_name,
    dr.route_id,
    EXTRACT(HOUR FROM fa.actual_departure)::INT   AS hour_ist,
    COUNT(*)                                       AS buses,
    ROUND(AVG(fa.headway_min)::NUMERIC, 2)         AS avg_headway_min,
    ROUND(MIN(fa.headway_min)::NUMERIC, 2)         AS min_headway_min,
    ROUND(MAX(fa.headway_min)::NUMERIC, 2)         AS max_headway_min,
    ROUND(STDDEV(fa.headway_min)::NUMERIC, 2)      AS stddev_headway,
    SUM(fa.is_bunched::INT)                        AS bunched_count,
    ROUND(100.0 * SUM(fa.is_bunched::INT)
          / NULLIF(COUNT(*), 0), 1)                AS bunching_rate_pct
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
WHERE fa.headway_min IS NOT NULL AND fa.headway_min > 0
GROUP BY dr.route_short_name, dr.route_id,
         EXTRACT(HOUR FROM fa.actual_departure);
CREATE INDEX IF NOT EXISTS idx_mv_hourly_route
    ON mv_hourly_headway (route_id, hour_ist);
REFRESH MATERIALIZED VIEW mv_hourly_headway;
CREATE OR REPLACE VIEW v_weather_otp AS
SELECT
    dd.full_date,
    fw.precipitation_mm,
    fw.temp_max_c,
    fw.is_rainy,
    dd.is_holiday,
    dd.is_weekend,
    COUNT(fa.id)                                              AS total_trips,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fa.is_on_time)
              / NULLIF(COUNT(fa.id), 0),
    1)                                                        AS fleet_otp_pct,
    ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)                  AS avg_delay_min
FROM fact_trip_actual fa
JOIN dim_date          dd ON dd.date_id   = fa.date_id
LEFT JOIN fact_weather_daily fw ON fw.date_id = fa.date_id
GROUP BY dd.full_date, fw.precipitation_mm, fw.temp_max_c,
         fw.is_rainy, dd.is_holiday, dd.is_weekend
ORDER BY dd.full_date;
