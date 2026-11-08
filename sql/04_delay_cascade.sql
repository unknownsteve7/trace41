-- =============================================================================
-- sql/04_delay_cascade.sql
-- Does delay at stop N propagate to stop N+1? Recursive CTE exploration.
-- Demonstrates: WITH RECURSIVE, self-join on stop_sequence.
-- =============================================================================

-- ── Recursive CTE: Delay cascade along stop sequence ─────────────────────────
-- For each trip, walk stop_sequence 1→2→3... and carry forward cumulative delay.
-- Uses fact_trip_schedule (scheduled times) + fact_trip_actual (actual departure).

WITH RECURSIVE stop_chain AS (

    -- Anchor: first stop on each trip
    SELECT
        fts.trip_id,
        fts.route_key,
        fts.stop_sequence,
        fts.stop_key,
        fts.arrival_time,
        -- Use actual trip delay at the route level as seed delay
        COALESCE(fta.delay_minutes, 0.0)   AS cumulative_delay,
        0                                   AS depth
    FROM fact_trip_schedule fts
    LEFT JOIN fact_trip_actual fta
           ON fta.trip_id  = fts.trip_id
    WHERE fts.stop_sequence = 1

    UNION ALL

    -- Recursive step: next stop (stop_sequence + 1)
    SELECT
        fts.trip_id,
        fts.route_key,
        fts.stop_sequence,
        fts.stop_key,
        fts.arrival_time,
        -- Each stop adds a small modelled propagation factor (0.1 min/stop)
        sc.cumulative_delay + 0.1           AS cumulative_delay,
        sc.depth + 1                        AS depth
    FROM fact_trip_schedule fts
    JOIN stop_chain sc
      ON  sc.trip_id       = fts.trip_id
      AND sc.stop_sequence = fts.stop_sequence - 1
    WHERE sc.depth < 50   -- safety cap (longest Delhi route has ~40 stops)
)
SELECT
    sc.trip_id,
    dr.route_short_name,
    sc.stop_sequence,
    ds.stop_name,
    sc.arrival_time                                              AS scheduled_arrival,
    ROUND(sc.cumulative_delay::NUMERIC, 2)                       AS est_cumulative_delay_min,
    -- Flag stops where delay exceeds 10 min threshold
    CASE WHEN sc.cumulative_delay > 10 THEN TRUE ELSE FALSE END  AS severely_delayed
FROM stop_chain sc
JOIN dim_route dr ON dr.route_key = sc.route_key
LEFT JOIN dim_stop ds ON ds.stop_key = sc.stop_key
ORDER BY sc.trip_id, sc.stop_sequence
LIMIT 500;

-- ── Simpler version: Date-spine CTE to fill missing daily data ─────────────────
-- Useful when a route had no buses on some days (gap-fill for time-series charts).
WITH date_spine AS (
    SELECT full_date, date_id
    FROM dim_date
    WHERE full_date BETWEEN CURRENT_DATE - INTERVAL '7 days' AND CURRENT_DATE
),
route_daily AS (
    SELECT
        fa.route_key,
        fa.date_id,
        COUNT(*)                              AS trips_actual,
        ROUND(AVG(fa.delay_minutes)::NUMERIC, 2) AS avg_delay
    FROM fact_trip_actual fa
    WHERE fa.delay_minutes IS NOT NULL
    GROUP BY fa.route_key, fa.date_id
)
SELECT
    dr.route_short_name,
    ds.full_date,
    COALESCE(rd.trips_actual, 0)             AS trips_actual,
    rd.avg_delay                             -- NULL if no service that day
FROM dim_route dr
CROSS JOIN date_spine ds
LEFT JOIN route_daily rd
       ON rd.route_key = dr.route_key
      AND rd.date_id   = ds.date_id
WHERE dr.is_current = TRUE
ORDER BY dr.route_short_name, ds.full_date;
