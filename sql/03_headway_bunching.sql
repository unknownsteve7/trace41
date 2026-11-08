-- =============================================================================
-- sql/03_headway_bunching.sql
-- Headway distribution and bunching detection per route.
-- Demonstrates: LAG(), ROWS BETWEEN, percentile aggregates.
-- =============================================================================

-- ── Query 1: Headway between successive buses (LAG window function) ────────────
-- Shows ROWS BETWEEN applied to ordered bus arrivals per route per day.
WITH ordered_buses AS (
    SELECT
        fa.trip_id,
        fa.vehicle_id,
        dr.route_short_name,
        dr.route_id,
        fa.date_id,
        fa.actual_departure,
        -- LAG: previous bus on the same route that day
        LAG(fa.actual_departure) OVER (
            PARTITION BY fa.route_key, fa.date_id
            ORDER BY fa.actual_departure
        ) AS prev_departure,
        fa.headway_min,
        fa.is_bunched
    FROM fact_trip_actual fa
    JOIN dim_route dr ON dr.route_key = fa.route_key
    WHERE fa.actual_departure IS NOT NULL
),
headway_stats AS (
    SELECT
        route_short_name,
        route_id,
        date_id,
        COUNT(*)                                                 AS buses_observed,
        ROUND(AVG(headway_min)::NUMERIC, 2)                      AS avg_headway_min,
        ROUND(MIN(headway_min)::NUMERIC, 2)                      AS min_headway_min,
        ROUND(MAX(headway_min)::NUMERIC, 2)                      AS max_headway_min,
        ROUND(STDDEV(headway_min)::NUMERIC, 2)                   AS stddev_headway,
        ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP
              (ORDER BY headway_min)::NUMERIC, 2)                AS median_headway_min,
        ROUND(PERCENTILE_CONT(0.9) WITHIN GROUP
              (ORDER BY headway_min)::NUMERIC, 2)                AS p90_headway_min,
        SUM(CASE WHEN is_bunched THEN 1 ELSE 0 END)              AS bunched_count,
        ROUND(100.0 * SUM(CASE WHEN is_bunched THEN 1 ELSE 0 END)
              / NULLIF(COUNT(*), 0), 1)                          AS bunching_rate_pct
    FROM ordered_buses
    WHERE headway_min IS NOT NULL AND headway_min > 0
    GROUP BY route_short_name, route_id, date_id
)
SELECT *
FROM headway_stats
ORDER BY bunching_rate_pct DESC;

-- ── Query 2: Running average headway using ROWS BETWEEN ───────────────────────
-- Shows how headway evolves across consecutive buses on a route.
SELECT
    fa.trip_id,
    dr.route_short_name,
    fa.actual_departure,
    fa.headway_min,
    -- 3-bus rolling average headway
    ROUND(AVG(fa.headway_min) OVER (
        PARTITION BY fa.route_key, fa.date_id
        ORDER BY fa.actual_departure
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    )::NUMERIC, 2)                                              AS rolling_3_avg_headway,
    -- Cumulative min headway seen so far
    MIN(fa.headway_min) OVER (
        PARTITION BY fa.route_key, fa.date_id
        ORDER BY fa.actual_departure
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )                                                           AS running_min_headway,
    fa.is_bunched
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
WHERE fa.headway_min IS NOT NULL
ORDER BY dr.route_short_name, fa.actual_departure;

-- ── Query 3: Bunching hotspots — worst routes by bunching rate ─────────────────
SELECT
    dr.route_short_name,
    COUNT(*)                                                     AS total_trips,
    SUM(fa.is_bunched::INT)                                      AS bunched_trips,
    ROUND(100.0 * SUM(fa.is_bunched::INT)
          / NULLIF(COUNT(*), 0), 1)                              AS bunching_rate_pct,
    ROUND(AVG(fa.headway_min)::NUMERIC, 2)                       AS avg_headway_min
FROM fact_trip_actual fa
JOIN dim_route dr ON dr.route_key = fa.route_key
WHERE fa.headway_min IS NOT NULL
GROUP BY dr.route_short_name
HAVING COUNT(*) >= 5
ORDER BY bunching_rate_pct DESC
LIMIT 15;
