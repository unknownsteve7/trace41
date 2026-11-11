SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('fact_trip_actual','fact_trip_schedule','dim_route','dim_stop','dim_date')
ORDER BY tablename, indexname;
EXPLAIN ANALYZE
SELECT
    dr.route_short_name,
    COUNT(*) FILTER (WHERE fa.is_on_time) AS on_time,
    COUNT(*)                              AS total
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
WHERE fa.delay_minutes IS NOT NULL
GROUP BY dr.route_short_name
ORDER BY total DESC
LIMIT 20;
CREATE INDEX IF NOT EXISTS idx_fta_delay_not_null
    ON fact_trip_actual (route_key, delay_minutes)
    WHERE delay_minutes IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fta_on_time
    ON fact_trip_actual (route_key, date_id)
    WHERE is_on_time IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fts_trip_stop
    ON fact_trip_schedule (trip_id, stop_sequence, stop_key);
EXPLAIN ANALYZE
SELECT
    dr.route_short_name,
    COUNT(*) FILTER (WHERE fa.is_on_time) AS on_time,
    COUNT(*)                              AS total
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
WHERE fa.delay_minutes IS NOT NULL
GROUP BY dr.route_short_name
ORDER BY total DESC
LIMIT 20;
EXPLAIN ANALYZE
SELECT
    fa.trip_id,
    fa.actual_departure,
    LAG(fa.actual_departure) OVER (
        PARTITION BY fa.route_key, fa.date_id
        ORDER BY fa.actual_departure
    ) AS prev_bus
FROM fact_trip_actual fa
WHERE fa.route_key IN (
    SELECT route_key FROM dim_route
    WHERE route_short_name LIKE '8%'
    LIMIT 5
);
SELECT
    relname  AS table_name,
    indexrelname AS index_name,
    idx_scan AS times_used,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
