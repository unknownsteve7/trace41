"""
dashboard/export_for_powerbi.py
───────────────────────────────
Exports aggregated datasets from PostgreSQL into clean CSVs
for direct import into Power BI Desktop.

Datasets generated in dashboard/export/:
  1. pbi_fleet_kpis.csv          (Fleet OTP, Avg Delay, Worst Routes)
  2. pbi_hourly_patterns.csv     (Hour of day × Delay & OTP)
  3. pbi_bunching_hotspots.csv   (Headway & bunching per route)
  4. pbi_complaints.csv          (Passenger QR feedback by category & route)
  5. pbi_ml_metrics.csv          (Feature importance & ML performance)
  6. pbi_route_map_stops.csv     (Bus stop coordinates for Power BI map visual)

Usage:
    python dashboard/export_for_powerbi.py
"""

import os
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
EXP  = ROOT / "dashboard" / "export"
EXP.mkdir(parents=True, exist_ok=True)

sslmode = os.getenv("PG_SSLMODE", "")
ssl_param = f" sslmode={sslmode}" if sslmode else ""
PG_DSN = (
    f"host={os.getenv('PG_HOST','localhost')} "
    f"port={os.getenv('PG_PORT','5432')} "
    f"dbname={os.getenv('PG_DATABASE','trace_db')} "
    f"user={os.getenv('PG_USER','postgres')} "
    f"password={os.getenv('PG_PASSWORD','trace_pass')}"
    + ssl_param
)

def run():
    print("=" * 60)
    print("TRACE — Exporting Data for Power BI Dashboard")
    print("=" * 60)

    with psycopg.connect(PG_DSN) as conn:
        # 1. Fleet KPIs & Worst Routes
        q1 = """
        SELECT
            dr.route_short_name,
            dr.route_id,
            COUNT(fa.id)                                  AS total_trips,
            COUNT(*) FILTER (WHERE fa.is_on_time = TRUE)  AS on_time_trips,
            ROUND(100.0 * COUNT(*) FILTER (WHERE fa.is_on_time = TRUE) / NULLIF(COUNT(fa.id), 0), 1) AS otp_pct,
            ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)      AS avg_delay_min,
            ROUND(AVG(fa.headway_min)::NUMERIC, 2)        AS avg_headway_min,
            SUM(fa.is_bunched::INT)                       AS bunched_count
        FROM fact_trip_actual fa
        JOIN dim_route dr ON dr.route_key = fa.route_key
        WHERE fa.delay_minutes IS NOT NULL
        GROUP BY dr.route_short_name, dr.route_id
        ORDER BY total_trips DESC;
        """
        df1 = pd.read_sql(q1, conn)
        df1.to_csv(EXP / "pbi_fleet_kpis.csv", index=False)
        print(f"  Exported {len(df1):,} rows -> pbi_fleet_kpis.csv")

        # 2. Hourly Patterns (24-hour Schedule vs Observed Live Adherence)
        q2 = """
        WITH hourly_sched AS (
            SELECT
                EXTRACT(HOUR FROM departure_time)::INT AS hour_of_day,
                COUNT(DISTINCT trip_id)                AS scheduled_trips,
                COUNT(*)                               AS scheduled_stops
            FROM fact_trip_schedule
            GROUP BY EXTRACT(HOUR FROM departure_time)
        ),
        hourly_actual AS (
            SELECT
                EXTRACT(HOUR FROM sched_departure)::INT AS hour_of_day,
                COUNT(fa.id)                            AS observed_trips,
                ROUND(100.0 * COUNT(*) FILTER (WHERE fa.is_on_time = TRUE) / NULLIF(COUNT(fa.id), 0), 1) AS otp_pct,
                ROUND(AVG(fa.delay_minutes)::NUMERIC, 2) AS avg_delay_min,
                ROUND(AVG(fa.headway_min)::NUMERIC, 2)   AS avg_headway_min
            FROM fact_trip_actual fa
            WHERE fa.sched_departure IS NOT NULL
            GROUP BY EXTRACT(HOUR FROM sched_departure)
        )
        SELECT
            s.hour_of_day AS hour_ist,
            COALESCE(a.observed_trips, 0) AS trips_observed,
            a.otp_pct,
            a.avg_delay_min,
            a.avg_headway_min,
            s.scheduled_trips,
            CASE
                WHEN s.hour_of_day BETWEEN 7 AND 10  THEN 'Morning Peak (07-10)'
                WHEN s.hour_of_day BETWEEN 16 AND 19 THEN 'Evening Peak (16-19)'
                WHEN s.hour_of_day BETWEEN 11 AND 15 THEN 'Mid-Day Base (11-15)'
                ELSE 'Night / Early Morning Off-Peak'
            END AS transit_period
        FROM hourly_sched s
        LEFT JOIN hourly_actual a ON a.hour_of_day = s.hour_of_day
        ORDER BY s.hour_of_day;
        """
        df2 = pd.read_sql(q2, conn)
        df2.to_csv(EXP / "pbi_hourly_patterns.csv", index=False)
        print(f"  Exported {len(df2):,} rows -> pbi_hourly_patterns.csv")

        # 3. Bunching Hotspots
        q3 = """
        SELECT
            dr.route_short_name,
            dr.route_id,
            COUNT(fa.id)                                  AS trips_observed,
            SUM(fa.is_bunched::INT)                       AS bunched_trips,
            ROUND(100.0 * SUM(fa.is_bunched::INT) / NULLIF(COUNT(fa.id), 0), 1) AS bunching_rate_pct,
            ROUND(AVG(fa.headway_min)::NUMERIC, 2)        AS avg_headway_min
        FROM fact_trip_actual fa
        JOIN dim_route dr ON dr.route_key = fa.route_key
        WHERE fa.headway_min IS NOT NULL
        GROUP BY dr.route_short_name, dr.route_id
        HAVING COUNT(fa.id) >= 3
        ORDER BY bunching_rate_pct DESC;
        """
        df3 = pd.read_sql(q3, conn)
        df3.to_csv(EXP / "pbi_bunching_hotspots.csv", index=False)
        print(f"  Exported {len(df3):,} rows -> pbi_bunching_hotspots.csv")

        # 4. Complaints
        q4 = """
        SELECT
            fc.complaint_id,
            dr.route_short_name,
            fc.category,
            fc.submitted_at,
            fc.complaint_text,
            fc.is_simulated
        FROM fact_complaints fc
        LEFT JOIN dim_route dr ON dr.route_key = fc.route_key;
        """
        df4 = pd.read_sql(q4, conn)
        df4.to_csv(EXP / "pbi_complaints.csv", index=False)
        print(f"  Exported {len(df4):,} rows -> pbi_complaints.csv")

        # 5. Stop coordinates for Mapping
        q5 = """
        SELECT
            stop_id,
            stop_name,
            lat,
            lon
        FROM dim_stop
        WHERE lat BETWEEN 28.40 AND 28.90 AND lon BETWEEN 76.80 AND 77.40
        LIMIT 2000;
        """
        df5 = pd.read_sql(q5, conn)
        df5.to_csv(EXP / "pbi_route_map_stops.csv", index=False)
        print(f"  Exported {len(df5):,} rows -> pbi_route_map_stops.csv")

        # 6. Daily Weather & Environmental Context
        q6 = """
        SELECT
            dd.full_date,
            dd.day_name,
            dd.is_weekend,
            dd.is_holiday,
            fw.temp_max_c,
            fw.temp_min_c,
            fw.precipitation_mm,
            fw.wind_max_kmph,
            fw.is_rainy
        FROM fact_weather_daily fw
        JOIN dim_date dd ON dd.date_id = fw.date_id
        ORDER BY dd.full_date;
        """
        df6 = pd.read_sql(q6, conn)
        df6.to_csv(EXP / "pbi_daily_weather.csv", index=False)
        print(f"  Exported {len(df6):,} rows -> pbi_daily_weather.csv")

    # 6. Copy ML feature importance
    ml_fi_path = ROOT / "data" / "ml" / "feature_importance.csv"
    if ml_fi_path.exists():
        fi_df = pd.read_csv(ml_fi_path)
        fi_df.to_csv(EXP / "pbi_ml_metrics.csv", index=False)
        print("  Exported ML metrics -> pbi_ml_metrics.csv")

    # 7. Write DataOps Heartbeat metadata (proves pipeline executed)
    heartbeat = {
        "last_sync_utc": datetime.now(timezone.utc).isoformat(),
        "status": "healthy",
        "total_routes_kpi": len(df1),
        "total_complaints": len(df4),
    }
    with open(EXP / "dataops_heartbeat.json", "w", encoding="utf-8") as f:
        json.dump(heartbeat, f, indent=2)
    print("  Updated DataOps Heartbeat -> dataops_heartbeat.json")

    print("\nAll Power BI CSV exports generated successfully in dashboard/export/ [OK]")

if __name__ == "__main__":
    run()
