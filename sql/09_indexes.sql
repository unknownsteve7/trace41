-- =============================================================================
-- sql/09_indexes.sql
-- Index tuning — EXPLAIN ANALYZE before/after demonstration.
-- Demonstrates: B-tree, composite indexes, EXPLAIN plan reading.
-- =============================================================================

-- ── BEFORE: Run EXPLAIN ANALYZE without indexes ───────────────────────────────
-- (indexes already created by 01_create_schema.sql, so this is a checkpoint)

-- Check which indexes exist currently
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('fact_trip_actual','fact_trip_schedule','dim_route','dim_stop','dim_date')
ORDER BY tablename, indexname;

-- ── EXPLAIN ANALYZE: Query 1 — OTP by route (before extra indexes) ────────────
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

-- ── Add targeted indexes ──────────────────────────────────────────────────────

-- Partial index: only rows where delay is known (used in almost every query)
CREATE INDEX IF NOT EXISTS idx_fta_delay_not_null
    ON fact_trip_actual (route_key, delay_minutes)
    WHERE delay_minutes IS NOT NULL;

-- Partial index: on-time filter (used in OTP queries)
CREATE INDEX IF NOT EXISTS idx_fta_on_time
    ON fact_trip_actual (route_key, date_id)
    WHERE is_on_time IS NOT NULL;

-- Composite index for schedule queries (trip stop lookup)
CREATE INDEX IF NOT EXISTS idx_fts_trip_stop
    ON fact_trip_schedule (trip_id, stop_sequence, stop_key);

-- ── EXPLAIN ANALYZE: Query 1 — AFTER indexes ──────────────────────────────────
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

-- ── EXPLAIN ANALYZE: Query 2 — Headway with LAG (window function) ─────────────
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

-- ── Index usage check ─────────────────────────────────────────────────────────
-- After running queries, check how many times each index was used:
SELECT
    relname  AS table_name,
    indexrelname AS index_name,
    idx_scan AS times_used,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;
