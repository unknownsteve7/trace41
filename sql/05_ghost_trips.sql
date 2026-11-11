SELECT COUNT(*) FILTER (WHERE trip_id IS NULL) AS null_trip_ids
FROM fact_trip_actual;
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
    WHERE fta.trip_id = fts.trip_id
)
GROUP BY fts.trip_id, dr.route_short_name, dr.route_id
ORDER BY scheduled_departure
LIMIT 50;
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
