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
from pathlib import Path
import pandas as pd
import psycopg
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
EXP  = ROOT / "dashboard" / "export"
EXP.mkdir(parents=True, exist_ok=True)

PG_DSN = (
    f"host={os.getenv('PG_HOST','localhost')} "
    f"port={os.getenv('PG_PORT','5432')} "
    f"dbname={os.getenv('PG_DATABASE','trace_db')} "
    f"user={os.getenv('PG_USER','postgres')} "
    f"password={os.getenv('PG_PASSWORD','trace_pass')}"
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

        # 2. Hourly Patterns
        q2 = """
        SELECT
            EXTRACT(HOUR FROM fa.actual_departure)::INT   AS hour_ist,
            COUNT(fa.id)                                  AS trips_observed,
            ROUND(100.0 * COUNT(*) FILTER (WHERE fa.is_on_time = TRUE) / NULLIF(COUNT(fa.id), 0), 1) AS otp_pct,
            ROUND(AVG(fa.delay_minutes)::NUMERIC, 2)      AS avg_delay_min,
            ROUND(AVG(fa.headway_min)::NUMERIC, 2)        AS avg_headway_min
        FROM fact_trip_actual fa
        WHERE fa.actual_departure IS NOT NULL AND fa.delay_minutes IS NOT NULL
        GROUP BY EXTRACT(HOUR FROM fa.actual_departure)
        ORDER BY hour_ist;
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

    # 6. Copy ML feature importance
    ml_fi_path = ROOT / "data" / "ml" / "feature_importance.csv"
    if ml_fi_path.exists():
        fi_df = pd.read_csv(ml_fi_path)
        fi_df.to_csv(EXP / "pbi_ml_metrics.csv", index=False)
        print("  Exported ML metrics -> pbi_ml_metrics.csv")

    print("\nAll Power BI CSV exports generated successfully in dashboard/export/ ✓")

if __name__ == "__main__":
    run()
