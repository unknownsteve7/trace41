CREATE OR REPLACE VIEW v_otp_by_route_hour AS
SELECT
    dr.route_short_name,
    dr.route_id,
    EXTRACT(HOUR FROM fa.actual_departure)::INT  AS hour_ist,
    COUNT(*)                                      AS trips_observed,
    COUNT(*) FILTER (WHERE fa.is_on_time = TRUE)  AS trips_on_time,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fa.is_on_time = TRUE) / NULLIF(COUNT(*), 0),
    1)                                            AS otp_pct,
    ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)      AS avg_delay_min,
    ROUND(MIN(fa.delay_minutes)::NUMERIC, 2)      AS min_delay_min,
    ROUND(MAX(fa.delay_minutes)::NUMERIC, 2)      AS max_delay_min,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fa.delay_minutes)::NUMERIC,
    2)                                            AS median_delay_min
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
WHERE fa.delay_minutes IS NOT NULL
GROUP BY dr.route_short_name, dr.route_id,
         EXTRACT(HOUR FROM fa.actual_departure);
SELECT
    route_short_name,
    route_id,
    SUM(trips_observed)                                        AS total_trips,
    ROUND(SUM(trips_on_time)::NUMERIC / NULLIF(SUM(trips_observed),0) * 100, 1)
                                                               AS overall_otp_pct,
    ROUND(AVG(avg_delay_min), 2)                               AS avg_delay_min,
    RANK() OVER (ORDER BY AVG(avg_delay_min) DESC)             AS delay_rank
FROM v_otp_by_route_hour
GROUP BY route_short_name, route_id
ORDER BY avg_delay_min DESC
LIMIT 10;
SELECT
    CASE
        WHEN hour_ist BETWEEN 7  AND 10 THEN 'Morning Peak (07-10)'
        WHEN hour_ist BETWEEN 17 AND 20 THEN 'Evening Peak (17-20)'
        WHEN hour_ist BETWEEN 11 AND 16 THEN 'Mid-Day (11-16)'
        ELSE                                 'Off-Peak'
    END                                             AS period,
    COUNT(*)                                        AS routes_in_period,
    SUM(trips_observed)                             AS total_trips,
    ROUND(
        100.0 * SUM(trips_on_time) / NULLIF(SUM(trips_observed), 0),
    1)                                              AS otp_pct,
    ROUND(AVG(avg_delay_min), 2)                    AS avg_delay_min
FROM v_otp_by_route_hour
GROUP BY period
ORDER BY avg_delay_min DESC;
SELECT
    dr.route_short_name,
    dd.day_name,
    COUNT(*)                                             AS trips,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE fa.is_on_time) / NULLIF(COUNT(*),0),
    1)                                                   AS otp_pct,
    ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)             AS avg_delay_min
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
JOIN dim_date  dd ON dd.date_id   = fa.date_id
WHERE fa.delay_minutes IS NOT NULL
GROUP BY ROLLUP(dr.route_short_name, dd.day_name)
ORDER BY dr.route_short_name, dd.day_name;
