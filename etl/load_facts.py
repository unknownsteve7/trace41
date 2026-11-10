"""
etl/load_facts.py
─────────────────
Loads all 4 fact tables into PostgreSQL Gold layer.

Loads (in order):
  1. fact_trip_schedule  — from silver/static/stop_times.parquet
  2. fact_trip_actual    — from silver/realtime/*.parquet (derived KPIs)
  3. fact_weather_daily  — from Open-Meteo API (no key needed)
  4. fact_complaints     — from data/complaints/simulated.csv

Usage:
    python etl/load_facts.py               # all facts
    python etl/load_facts.py schedule      # only schedule
    python etl/load_facts.py actual        # only actual
    python etl/load_facts.py weather       # only weather
    python etl/load_facts.py complaints    # only complaints
"""

import sys
import math
import logging
import os
import csv
import uuid
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests
import psycopg
from dotenv import load_dotenv

load_dotenv()

ROOT      = Path(__file__).resolve().parent.parent
SILVER    = ROOT / "data" / "silver"
(SILVER / "realtime").mkdir(parents=True, exist_ok=True)
COMPL_CSV = ROOT / "data" / "complaints" / "simulated.csv"

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("load_facts")

BATCH = 5000  # rows per INSERT batch


def _batch_insert(conn, sql: str, rows: list):
    if not rows:
        return
    with conn.cursor() as cur:
        for i in range(0, len(rows), BATCH):
            cur.executemany(sql, rows[i:i+BATCH])
    conn.commit()


def _get_route_key_map(conn) -> dict:
    """Returns {route_id: route_key} for current routes."""
    with conn.cursor() as cur:
        cur.execute("SELECT route_id, route_key FROM dim_route WHERE is_current=TRUE")
        return {r[0]: r[1] for r in cur.fetchall()}


def _get_stop_key_map(conn) -> dict:
    """Returns {stop_id: stop_key}."""
    with conn.cursor() as cur:
        cur.execute("SELECT stop_id, stop_key FROM dim_stop")
        return {r[0]: r[1] for r in cur.fetchall()}


def _get_date_id_map(conn) -> dict:
    """Returns {'YYYY-MM-DD': date_id}."""
    with conn.cursor() as cur:
        cur.execute("SELECT full_date::text, date_id FROM dim_date")
        return {r[0]: r[1] for r in cur.fetchall()}


# ── 1. fact_trip_schedule ─────────────────────────────────────────────────────
def load_schedule(conn):
    p = SILVER / "static" / "stop_times.parquet"
    if not p.exists():
        log.error("stop_times.parquet not found. Run static_to_silver.py first.")
        return

    log.info("Loading fact_trip_schedule using fast vectorization ...")
    route_map  = _get_route_key_map(conn)
    stop_map   = _get_stop_key_map(conn)
    date_map   = _get_date_id_map(conn)

    service_date = str(date.today())
    date_id = date_map.get(service_date) or date_map.get("2026-11-08") or 1

    df = pd.read_parquet(p)
    log.info(f"  {len(df):,} stop_time rows in silver parquet ...")

    # Map trips to routes
    trips_p = SILVER / "static" / "trips.parquet"
    if trips_p.exists():
        tdf = pd.read_parquet(trips_p)[["trip_id","route_id"]]
        trip_to_route = dict(zip(tdf["trip_id"], tdf["route_id"]))
    else:
        trip_to_route = {}

    df["route_id"] = df["trip_id"].map(trip_to_route).fillna(df.get("route_id", ""))
    df["route_key"] = df["route_id"].astype(str).map(route_map)
    df["stop_key"]  = df["stop_id"].astype(str).map(stop_map)
    df["date_id"]   = date_id

    arr_col = "arrival_time_norm" if "arrival_time_norm" in df.columns else "arrival_time"
    dep_col = "departure_time_norm" if "departure_time_norm" in df.columns else "departure_time"
    day_col = "arrival_day_offset" if "arrival_day_offset" in df.columns else "arrival_day_off"

    df["arr"] = df[arr_col].fillna("")
    df["dep"] = df[dep_col].fillna("")
    df["day_off"] = df[day_col].fillna(0).astype(int)
    df["stop_sequence"] = pd.to_numeric(df["stop_sequence"], errors="coerce").fillna(0).astype(int)

    # Filter out empty trip_id
    df = df[df["trip_id"].notna() & (df["trip_id"] != "")].copy()
    log.info(f"  Preparing CSV stream for {len(df):,} rows ...")

    import io
    buf = io.StringIO()
    # Write tab-separated without headers
    sub = df[["trip_id", "route_key", "date_id", "stop_sequence", "stop_key", "arr", "dep", "day_off"]]
    # Format route_key and stop_key as empty string if NaN
    sub.to_csv(buf, sep="\t", header=False, index=False, na_rep="")
    buf.seek(0)

    log.info("  Executing bulk COPY into fact_trip_schedule ...")
    with conn.cursor() as cur:
        with cur.copy(
            "COPY fact_trip_schedule (trip_id, route_key, date_id, stop_sequence, stop_key, arrival_time, departure_time, arrival_day_off) FROM STDIN WITH (FORMAT csv, DELIMITER '\t', NULL '')"
        ) as copy:
            while data := buf.read(65536):
                copy.write(data)
    conn.commit()
    log.info(f"  fact_trip_schedule loaded {len(df):,} rows successfully ✓")


# ── 2. fact_trip_actual ───────────────────────────────────────────────────────
def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlam/2)**2
    return 2 * R * math.asin(math.sqrt(a))


def _derive_actual_kpis(df: pd.DataFrame, route_map: dict) -> pd.DataFrame:
    """
    Given a day's realtime silver DataFrame, derive:
      - First/last ping per trip → actual_departure
      - Delay vs nearest scheduled slot
      - Headway (time between successive buses, same route, same hour window)
      - Bunching flag
      - Avg speed
    Returns one row per (trip_id, vehicle_id).
    """
    df = df.copy()
    df["vehicle_dt_ist"] = pd.to_datetime(df["vehicle_dt_ist"], utc=False, errors="coerce")
    df = df.sort_values(["trip_id", "vehicle_dt_ist"])

    # Aggregate per trip × vehicle
    agg = df.groupby(["trip_id","vehicle_id","trip_route_id","date_ist",
                       "sched_HH","sched_MM"], dropna=False).agg(
        first_seen=("vehicle_dt_ist","min"),
        last_seen=("vehicle_dt_ist","max"),
        ping_count=("vehicle_id","count"),
    ).reset_index()

    # Actual departure = first ping time
    agg["actual_departure"] = agg["first_seen"].dt.strftime("%H:%M:%S")
    agg["sched_departure"] = agg.apply(
        lambda r: f"{int(r['sched_HH']):02d}:{int(r['sched_MM']):02d}:00"
        if pd.notna(r["sched_HH"]) and pd.notna(r["sched_MM"]) else None, axis=1
    )

    # Delay in minutes
    def _delay(row):
        try:
            a = datetime.strptime(row["actual_departure"], "%H:%M:%S")
            s = datetime.strptime(row["sched_departure"],  "%H:%M:%S")
            return (a - s).total_seconds() / 60
        except Exception:
            return None

    agg["delay_minutes"] = agg.apply(_delay, axis=1)
    agg["is_on_time"]    = agg["delay_minutes"].apply(
        lambda d: (abs(d) <= 5) if d is not None and not math.isnan(d) else None
    )

    # Route key
    agg["route_key"] = agg["trip_route_id"].map(route_map)

    # Headway: sort by route × actual_departure, LAG-style
    agg = agg.sort_values(["trip_route_id","first_seen"])
    agg["prev_seen"] = agg.groupby("trip_route_id")["first_seen"].shift(1)
    agg["headway_min"] = (
        (agg["first_seen"] - agg["prev_seen"]).dt.total_seconds() / 60
    )
    agg["is_bunched"] = agg["headway_min"] < 2.0

    # Confidence
    def _conf(n):
        if n >= 10: return "HIGH"
        if n >= 3:  return "MED"
        return "LOW"
    agg["confidence"] = agg["ping_count"].apply(_conf)

    # Avg speed requires sequential ping analysis — approximate from df
    speed_map = {}
    for (tid, vid), grp in df.groupby(["trip_id","vehicle_id"]):
        grp = grp.sort_values("vehicle_dt_ist")
        lats = grp["lat"].tolist(); lons = grp["lon"].tolist()
        times = grp["vehicle_dt_ist"].tolist()
        total_dist = 0.0; total_secs = 0.0
        for i in range(1, len(lats)):
            if None in (lats[i-1], lons[i-1], lats[i], lons[i]):
                continue
            try:
                total_dist += _haversine_km(lats[i-1], lons[i-1], lats[i], lons[i])
                total_secs += (times[i] - times[i-1]).total_seconds()
            except Exception:
                pass
        speed_map[(tid, vid)] = (total_dist / (total_secs/3600)) if total_secs > 0 else None

    agg["avg_speed_kmph"] = agg.apply(
        lambda r: speed_map.get((r["trip_id"], r["vehicle_id"])), axis=1
    )

    return agg


def load_actual(conn):
    rt_dir = SILVER / "realtime"
    pq_files = sorted(rt_dir.glob("*.parquet"))
    if not pq_files:
        log.warning("No realtime parquet files found. Run realtime_to_silver.py first.")
        return

    route_map = _get_route_key_map(conn)
    date_map  = _get_date_id_map(conn)

    for pq_path in pq_files:
        date_str = pq_path.stem
        log.info(f"  Processing {date_str} ...")
        df = pd.read_parquet(pq_path)

        if df.empty:
            log.warning(f"    No rows in {pq_path.name}")
            continue

        agg = _derive_actual_kpis(df, route_map)
        date_id = date_map.get(date_str)
        if date_id is None:
            log.warning(f"    {date_str} not in dim_date — skipping")
            continue

        def _clean_float(val):
            if pd.notna(val):
                try:
                    f = float(val)
                    return None if math.isnan(f) or math.isinf(f) else f
                except (ValueError, TypeError):
                    return None
            return None

        def _clean_int(val):
            if pd.notna(val):
                try:
                    f = float(val)
                    return None if math.isnan(f) or math.isinf(f) else int(f)
                except (ValueError, TypeError):
                    return None
            return None

        rows = []
        for _, r in agg.iterrows():
            rows.append((
                str(r["trip_id"]) if pd.notna(r["trip_id"]) else None,
                str(r["vehicle_id"]) if pd.notna(r["vehicle_id"]) else None,
                _clean_int(r.get("route_key")),
                _clean_int(date_id),
                str(r["actual_departure"]) if pd.notna(r.get("actual_departure")) else None,
                str(r["sched_departure"]) if pd.notna(r.get("sched_departure")) else None,
                _clean_float(r.get("delay_minutes")),
                bool(r["is_on_time"]) if pd.notna(r.get("is_on_time")) else None,
                _clean_float(r.get("headway_min")),
                bool(r["is_bunched"]) if pd.notna(r.get("is_bunched")) else None,
                _clean_float(r.get("avg_speed_kmph")),
                _clean_int(r.get("ping_count")),
                str(r["confidence"]) if pd.notna(r.get("confidence")) else None,
            ))

        _batch_insert(conn,
            """INSERT INTO fact_trip_actual
               (trip_id, vehicle_id, route_key, date_id,
                actual_departure, sched_departure, delay_minutes,
                is_on_time, headway_min, is_bunched,
                avg_speed_kmph, ping_count, confidence)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (trip_id, vehicle_id) DO UPDATE SET
                actual_departure = EXCLUDED.actual_departure,
                sched_departure = EXCLUDED.sched_departure,
                delay_minutes = EXCLUDED.delay_minutes,
                is_on_time = EXCLUDED.is_on_time,
                headway_min = EXCLUDED.headway_min,
                is_bunched = EXCLUDED.is_bunched,
                avg_speed_kmph = EXCLUDED.avg_speed_kmph,
                ping_count = EXCLUDED.ping_count,
                confidence = EXCLUDED.confidence""",
            rows
        )
        log.info(f"    → Loaded {len(rows)} trip-actual rows for {date_str} ✓")

    log.info("fact_trip_actual loaded ✓")


# ── 3. fact_weather_daily ─────────────────────────────────────────────────────
def load_weather(conn):
    """Fetch historical daily weather from Open-Meteo (no API key needed)."""
    log.info("Loading fact_weather_daily from Open-Meteo ...")

    lat  = float(os.getenv("WEATHER_LAT", "28.6139"))
    lon  = float(os.getenv("WEATHER_LON", "77.2090"))
    url  = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "past_days":       92,
        "forecast_days":   1,
        "daily":           "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
        "timezone":        "Asia/Kolkata",
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()["daily"]
    except Exception as e:
        log.error(f"  Open-Meteo fetch failed: {e}")
        return

    date_map = _get_date_id_map(conn)
    rows = []
    for i, d in enumerate(data["time"]):
        date_id = date_map.get(d)
        if date_id is None:
            continue
        rows.append((
            date_id,
            data["temperature_2m_max"][i],
            data["temperature_2m_min"][i],
            data["precipitation_sum"][i],
            data["wind_speed_10m_max"][i],
        ))

    _batch_insert(conn,
        """INSERT INTO fact_weather_daily
           (date_id, temp_max_c, temp_min_c, precipitation_mm, wind_max_kmph)
           VALUES (%s,%s,%s,%s,%s)
           ON CONFLICT (date_id) DO NOTHING""",
        rows
    )
    log.info(f"  Loaded {len(rows)} weather rows ✓")


# ── 4. fact_complaints ────────────────────────────────────────────────────────
def load_complaints(conn):
    """Load simulated complaints from CSV."""
    if not COMPL_CSV.exists():
        log.warning(f"  {COMPL_CSV} not found. Run simulate_complaints.py first (or skip).")
        return

    log.info("Loading fact_complaints ...")
    route_map = _get_route_key_map(conn)
    date_map  = _get_date_id_map(conn)

    rows = []
    with open(COMPL_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            route_key = route_map.get(r.get("route_id",""))
            date_id   = date_map.get(r.get("date",""))
            submitted = r.get("submitted_at") or None
            rows.append((
                r.get("complaint_id") or str(uuid.uuid4()),
                route_key,
                date_id,
                r.get("stop_id") or None,
                r.get("vehicle_id") or None,
                r.get("category") or None,
                r.get("complaint_text") or None,
                submitted,
                True,  # is_simulated
            ))

    _batch_insert(conn,
        """INSERT INTO fact_complaints
           (complaint_id, route_key, date_id, stop_id, vehicle_id,
            category, complaint_text, submitted_at, is_simulated)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (complaint_id) DO NOTHING""",
        rows
    )
    log.info(f"  Loaded {len(rows)} complaint rows ✓")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("TRACE — Load Facts → PostgreSQL")
    log.info("=" * 60)

    target = sys.argv[1] if len(sys.argv) > 1 else "all"

    with psycopg.connect(PG_DSN) as conn:
        if target in ("all", "schedule"):
            load_schedule(conn)
        if target in ("all", "actual"):
            load_actual(conn)
        if target in ("all", "weather"):
            load_weather(conn)
        if target in ("all", "complaints"):
            load_complaints(conn)

    log.info("All requested facts loaded ✓")


if __name__ == "__main__":
    main()
