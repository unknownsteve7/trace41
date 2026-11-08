-- =============================================================================
-- sql/05_ghost_trips.sql
-- Scheduled trips that never appeared in the live feed (ghost/cancelled trips).
-- Demonstrates: NOT EXISTS anti-join, NOT IN NULL-trap, outer join approach.
-- =============================================================================

-- ── The NULL Trap Demo — Why NOT IN fails with NULLs ─────────────────────────
-- If fact_trip_actual.trip_id contains even one NULL, NOT IN returns no rows.
-- This block PROVES the trap exists, then shows the safe alternatives.

-- STEP 1: Count NULLs in trip_id (there may be none, but the risk is real)
SELECT COUNT(*) FILTER (WHERE trip_id IS NULL) AS null_trip_ids
FROM fact_trip_actual;

-- STEP 2: Dangerous approach (DO NOT USE in production — shown for learning)
-- If any trip_id in fact_trip_actual is NULL, this returns ZERO rows always:
/*
SELECT trip_id FROM fact_trip_schedule
WHERE trip_id NOT IN (SELECT trip_id FROM fact_trip_actual);
-- ^ BROKEN if any trip_id is NULL in subquery
*/

-- STEP 3: Safe anti-join with NOT EXISTS (NULL-safe, recommended) ──────────────
-- Finds scheduled trips that have NO matching actual trip observed in the feed.
SELECT
    fts.trip_id,
    dr.route_short_name,
    dr.route_id,
    MIN(fts.departure_time)                       AS scheduled_departure,
    COUNT(DISTINCT fts.stop_sequence)             AS stop_count,
    'NOT EXISTS anti-join'                        AS method
FROM fact_trip_schedule fts
JOIN dim_route dr ON dr.route_key = fts.route_key
WHERE NOT EXISTS (
    SELECT 1
    FROM fact_trip_actual fta
    WHERE fta.trip_id = fts.trip_id  -- correlated, NULL-safe
)
GROUP BY fts.trip_id, dr.route_short_name, dr.route_id
ORDER BY scheduled_departure
LIMIT 50;

-- STEP 4: Alternative — LEFT JOIN / IS NULL (also NULL-safe) ──────────────────
SELECT
    fts.trip_id,
    dr.route_short_name,
    MIN(fts.departure_time)                       AS scheduled_departure,
    'LEFT JOIN IS NULL'                           AS method
FROM fact_trip_schedule fts
JOIN dim_route dr ON dr.route_key = fts.route_key
LEFT JOIN fact_trip_actual fta ON fta.trip_id = fts.trip_id
WHERE fta.trip_id IS NULL
GROUP BY fts.trip_id, dr.route_short_name
ORDER BY scheduled_departure
LIMIT 50;

-- STEP 5: Ghost trip summary by route ─────────────────────────────────────────
-- Which routes have the most cancellations/no-shows?
SELECT
    dr.route_short_name,
    COUNT(DISTINCT fts.trip_id)                                  AS scheduled_trips,
    COUNT(DISTINCT fta.trip_id)                                  AS actual_trips,
    COUNT(DISTINCT fts.trip_id) - COUNT(DISTINCT fta.trip_id)   AS ghost_trips,
    ROUND(
        100.0 * (COUNT(DISTINCT fts.trip_id) - COUNT(DISTINCT fta.trip_id))
              / NULLIF(COUNT(DISTINCT fts.trip_id), 0),
    1)                                                           AS ghost_rate_pct
FROM fact_trip_schedule fts
JOIN dim_route dr ON dr.route_key = fts.route_key
LEFT JOIN fact_trip_actual fta ON fta.trip_id = fts.trip_id
GROUP BY dr.route_short_name
HAVING COUNT(DISTINCT fts.trip_id) >= 3
ORDER BY ghost_rate_pct DESC
LIMIT 20;
