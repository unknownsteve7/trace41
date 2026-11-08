# TRACE: Transit Analytics & Reliability Correlation Engine
**An End-to-End Reliability, Root-Cause & Feedback Analytics System for Delhi's Bus Network**

TRACE is a transit data analytics platform that measures, explains, and models the reliability of public bus transit in Delhi using official Open Transit Data (OTD) feeds, static General Transit Feed Specification (GTFS), Open-Meteo weather intelligence, and passenger feedback.

---

## 🏛️ System Architecture

TRACE follows the **Medallion Data Lakehouse Architecture** backed by PostgreSQL:

```mermaid
flowchart TD
    subgraph Data Sources
        S1["Delhi OTD Portal\nGTFS-RT VehiclePositions.pb\n(Every 30s)"]
        S2["Static GTFS\n(routes, trips, stops,\nstop_times, shapes)"]
        S3["Open-Meteo API\n(Daily Precipitation,\nWind, Temperature)"]
        S4["Simulated Passenger Layer\n(QR-Based Complaints)"]
    end

    subgraph Bronze Layer
        B1["Raw .pb Snapshots\ndata/raw/YYYY-MM-DD/*.pb\n(Immutable)"]
    end

    subgraph Silver Layer
        SL1["Cleaned Parquet\ndata/silver/realtime/*.parquet\n(Deduped, Stale & Outliers Flagged)"]
        SL2["GTFS Parquet\ndata/silver/static/*.parquet\n(24:00+ Times Normalized)"]
        Q["Quarantine\ndata/quarantine/*.parquet"]
    end

    subgraph Gold Layer (PostgreSQL Star Schema)
        D1[("dim_route\n(SCD Type 2)")]
        D2[("dim_stop")]
        D3[("dim_date\n(Holidays & Weekends)")]
        F1[("fact_trip_actual")]
        F2[("fact_trip_schedule")]
        F3[("fact_weather_daily")]
        F4[("fact_complaints")]
    end

    subgraph Analytics & Consumption
        A1["Advanced SQL\n(CTEs, Window Frames,\nAnti-joins, MatViews)"]
        A2["Statistical Validation\n(Mann-Whitney U,\nSpearman Correlation)"]
        A3["ML Delay Prediction\n(RandomForest Pilot Model)"]
        A4["Power BI\n(5-Page Interactive Dashboard)"]
    end

    S1 --> B1 --> SL1
    S2 --> SL2
    B1 -. Outliers .-> Q
    SL1 --> F1
    SL2 --> D1 & D2 & F2
    S3 --> F3
    S4 --> F4
    F1 & F2 & F3 & F4 --> A1 & A2 & A3 & A4
```

---

## 📊 Database Schema (Gold Layer)

The analytics warehouse is designed in PostgreSQL (`trace_db`) as a high-performance **Star Schema**:

| Table | Type | Rows | Description |
|---|---|---|---|
| [`dim_date`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Dimension | 365 | 2026 Calendar, Day of week, Indian National Holidays flag |
| [`dim_route`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Dimension | 2,554 | Bus routes, terminals, SCD Type 2 validity |
| [`dim_stop`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Dimension | 6,812 | Bus stops with GPS coordinates (lat/lon) |
| [`fact_trip_schedule`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Fact | **2,385,381** | Scheduled stop arrival and departure timetable |
| [`fact_trip_actual`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Fact | **4,792+** | Actual observed bus trips, delay minutes, headway, bunching flags |
| [`fact_weather_daily`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Fact | 93 | Daily max/min temperature, precipitation (mm), wind speed |
| [`fact_complaints`](file:///c:/Users/nagam/z_world/trace41/trace41/sql/01_create_schema.sql) | Fact | 200 | Passenger feedback mapped to route and category (simulated) |

---

## 🔍 Key Discoveries & Technical Insights

1. **Delhi Dispatch Mechanism Decoded**:
   Live GTFS-RT feed generates dynamic trip IDs: `trip_id = <route_id>_<actual_hour>_<actual_minute>`.
   - **98.3% Route match**: Buses running live match the static GTFS route network.
   - **86.8% Schedule Alignment**: 86.8% of live dispatches depart within $\pm 15$ minutes of an official scheduled timetable slot on that route.

2. **Bunching & Headway Dynamics**:
   - Spearman rank correlation ($\rho = -0.481, p < 0.001$) shows a statistically significant relationship between average headway and bunching rate: routes with high dispatch frequency suffer dramatic bunching when headway drops under 2 minutes.

3. **Machine Learning Delay Prediction**:
   - Random Forest model achieves **83.7% accuracy** on delay classification and **MAE of 39.2 minutes** (outperforming the naive baseline of 44.1 minutes).
   - Top feature importances: Route profile (68.8%), Headway gap (24.7%), and GPS ping density (6.5%).

---

## 💻 SQL Analysis Portfolio

The project exercises key relational database engineering concepts:

- **Window Functions & Frame Clauses** (`sql/02_otp_by_route.sql`, `sql/03_headway_bunching.sql`):
  Uses `LAG()` to calculate headway between consecutive buses, and `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` to compute rolling 3-bus average headway.
- **NULL-Safe Anti-Joins** (`sql/05_ghost_trips.sql`):
  Demonstrates why naive `NOT IN` fails when subqueries contain NULLs (the NULL trap), and implements production-grade `NOT EXISTS` anti-joins to identify scheduled "ghost trips" that failed to dispatch.
- **Recursive CTEs** (`sql/04_delay_cascade.sql`):
  Walks the stop sequence ($1 \to 2 \to \dots \to n$) using `WITH RECURSIVE` to model cumulative delay propagation along the route corridor.
- **Materialized Views & Stored Procedures** (`sql/07_views_matview.sql`, `sql/08_stored_proc.sql`):
  Cached views (`mv_hourly_headway`) refreshed via automated PL/pgSQL procedures (`sp_load_realtime_day`).
- **Index Tuning & Query Plans** (`sql/09_indexes.sql`):
  `EXPLAIN ANALYZE` comparisons showing index scan speedups on large fact table joins.

---

## 📱 QR-Based Passenger Complaint System

To close the loop between measured delay and rider perception:
- Sample branded QR cards are generated in [`qr/sample_qr_bus_interior.png`](file:///c:/Users/nagam/z_world/trace41/trace41/qr/sample_qr_bus_interior.png) and [`qr/sample_qr_bus_stop.png`](file:///c:/Users/nagam/z_world/trace41/trace41/qr/sample_qr_bus_stop.png).
- Scanning the QR opens a pre-filled complaint form embedding `route_id`, `stop_id`, and `vehicle_id`.
- Riders submit categorised feedback (Late Arrival, Overcrowding, No Show, Driver Behavior) linked back to `fact_complaints`.

---

## 📈 Power BI Dashboard Setup

Ready-to-import CSV files are generated in `dashboard/export/`:
1. `pbi_fleet_kpis.csv`: Fleet-wide On-Time Performance (OTP) and delay rank.
2. `pbi_hourly_patterns.csv`: Delay and reliability across peak vs off-peak hours.
3. `pbi_bunching_hotspots.csv`: Worst bunched routes and headway variances.
4. `pbi_complaints.csv`: Category distribution and route complaint counts.
5. `pbi_ml_metrics.csv`: Feature importances and accuracy benchmarks.
6. `pbi_route_map_stops.csv`: Stop coordinates for Delhi route map visualization.

See [`docs/powerbi_setup_guide.md`](file:///c:/Users/nagam/z_world/trace41/trace41/docs/powerbi_setup_guide.md) for step-by-step dashboard creation instructions.

---

## 🛡️ Limitations & Intellectual Honesty

1. **Pilot Dataset Scope**: Real-time vehicle positions cover a multi-day observation window. Findings represent an empirical pilot study rather than multi-year seasonal trends.
2. **Dynamic Dispatch Logic**: While DTC buses match static routes at 98.3%, Delhi operates dynamic depot dispatching rather than fixed-second adherence.
3. **Synthetic Feedback**: The QR complaint dataset is simulated for design demonstration and should not be cited as real passenger grievance records.
