"""
etl/realtime_to_silver.py
─────────────────────────
Decodes all raw .pb files in data/raw/ → Silver Parquet per day.

Transformations applied:
  - Parse gtfs_realtime_pb2.FeedMessage from each .pb file
  - Dedup on (vehicle_id, vehicle_timestamp)
  - Flag stale pings (poll_ts - vehicle_timestamp > 300s)
  - Flag out-of-bbox lat/lon (Delhi bounds), quarantine those rows
  - Parse trip_id -> route_id + scheduled_HH + scheduled_MM
  - Write data/silver/realtime/YYYY-MM-DD.parquet (incremental: skip existing)

Usage:
    python etl/realtime_to_silver.py              # process all days
    python etl/realtime_to_silver.py 2026-11-08   # specific day only
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from google.transit import gtfs_realtime_pb2

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parent.parent
RAW_DIR      = ROOT / "data" / "raw"
SILVER_RT    = ROOT / "data" / "silver" / "realtime"
QUARANTINE   = ROOT / "data" / "quarantine"
SILVER_RT.mkdir(parents=True, exist_ok=True)
QUARANTINE.mkdir(parents=True, exist_ok=True)

# Delhi bounding box
DELHI_LAT_MIN, DELHI_LAT_MAX = 28.40, 28.90
DELHI_LON_MIN, DELHI_LON_MAX = 76.80, 77.40
STALE_THRESHOLD_S = 300  # 5 minutes

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("realtime_to_silver")


# ── Core parse ────────────────────────────────────────────────────────────────
def parse_pb(pb_path: Path) -> list[dict]:
    """Parse one .pb file into a list of vehicle-position dicts."""
    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(pb_path.read_bytes())
    except Exception as e:
        log.warning(f"  Could not parse {pb_path.name}: {e}")
        return []

    # Feed-level timestamp = poll time (server confirmed)
    poll_ts = feed.header.timestamp or 0
    rows = []
    for entity in feed.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        vid       = v.vehicle.id or entity.id
        vts       = v.timestamp or 0
        lat       = v.position.latitude  if v.HasField("position") else None
        lon       = v.position.longitude if v.HasField("position") else None
        speed     = v.position.speed     if v.HasField("position") else None
        trip_id   = v.trip.trip_id  or ""
        route_id  = v.trip.route_id or ""

        rows.append({
            "vehicle_id":        vid,
            "vehicle_timestamp": vts,
            "poll_timestamp":    poll_ts,
            "pb_file":           pb_path.name,
            "trip_id":           trip_id,
            "route_id":          route_id,
            "lat":               lat,
            "lon":               lon,
            "speed_ms":          speed,
        })
    return rows


def process_day(date_str: str, overwrite: bool = False) -> dict:
    """
    Process all .pb files for a given YYYY-MM-DD date.
    Returns a summary dict for the run log.
    """
    day_dir = RAW_DIR / date_str
    out_path = SILVER_RT / f"{date_str}.parquet"

    if out_path.exists() and not overwrite:
        log.info(f"[{date_str}] Silver already exists — skipping (use overwrite=True to reprocess)")
        return {"date": date_str, "status": "skipped"}

    pb_files = sorted(day_dir.glob("*.pb")) if day_dir.exists() else []
    if not pb_files:
        log.warning(f"[{date_str}] No .pb files found in {day_dir}")
        return {"date": date_str, "status": "no_data"}

    log.info(f"[{date_str}] Processing {len(pb_files)} .pb files ...")

    all_rows = []
    for pb_path in pb_files:
        all_rows.extend(parse_pb(pb_path))

    if not all_rows:
        log.warning(f"[{date_str}] Zero rows parsed.")
        return {"date": date_str, "status": "empty"}

    df = pd.DataFrame(all_rows)
    raw_count = len(df)

    # ── 1. Dedup on (vehicle_id, vehicle_timestamp) ──────────────────────────
    df = df.drop_duplicates(subset=["vehicle_id", "vehicle_timestamp"])
    dedup_count = len(df)
    log.info(f"  Rows after dedup: {dedup_count:,} (removed {raw_count - dedup_count:,})")

    # ── 2. Stale flag ─────────────────────────────────────────────────────────
    df["is_stale"] = (df["poll_timestamp"] - df["vehicle_timestamp"]) > STALE_THRESHOLD_S

    # ── 3. Bbox flag ──────────────────────────────────────────────────────────
    df["out_of_bbox"] = ~(
        df["lat"].between(DELHI_LAT_MIN, DELHI_LAT_MAX) &
        df["lon"].between(DELHI_LON_MIN, DELHI_LON_MAX)
    )
    quarantine_df = df[df["out_of_bbox"] | df["lat"].isna()]
    if len(quarantine_df):
        qpath = QUARANTINE / f"{date_str}.parquet"
        quarantine_df.to_parquet(qpath, index=False, engine="pyarrow")
        log.warning(f"  Quarantined {len(quarantine_df):,} rows -> {qpath.name}")
    df = df[~df["out_of_bbox"] & df["lat"].notna()]

    # ── 4. Parse trip_id → route + schedule time ──────────────────────────────
    # Format: <route_id>_<H>_<M>
    parts = df["trip_id"].str.split("_", n=2, expand=True)
    df["trip_route_id"] = parts[0].where(parts[0].notna(), df["route_id"])
    df["sched_HH"]      = pd.to_numeric(parts[1], errors="coerce")
    df["sched_MM"]      = pd.to_numeric(parts[2], errors="coerce")

    # ── 5. Convert timestamps to readable UTC ─────────────────────────────────
    df["vehicle_dt_utc"] = pd.to_datetime(df["vehicle_timestamp"], unit="s", utc=True)
    df["poll_dt_utc"]    = pd.to_datetime(df["poll_timestamp"],    unit="s", utc=True)

    # IST offset +5:30
    df["vehicle_dt_ist"] = df["vehicle_dt_utc"] + pd.Timedelta(hours=5, minutes=30)
    df["hour_ist"]       = df["vehicle_dt_ist"].dt.hour
    df["date_ist"]       = df["vehicle_dt_ist"].dt.date.astype(str)

    # ── Save ──────────────────────────────────────────────────────────────────
    df.to_parquet(out_path, index=False, engine="pyarrow")
    log.info(f"  -> Saved {out_path.name}  ({len(df):,} rows)")

    return {
        "date":        date_str,
        "status":      "ok",
        "raw_rows":    raw_count,
        "clean_rows":  len(df),
        "quarantined": len(quarantine_df),
        "pb_files":    len(pb_files),
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("TRACE — Realtime .pb → Silver Parquet")
    log.info("=" * 60)

    overwrite = "--overwrite" in sys.argv or "-f" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--overwrite", "-f")]

    if args:
        dates = [args[0]]
    else:
        # All dated subdirectories in data/raw/
        dates = sorted(d.name for d in RAW_DIR.iterdir() if d.is_dir())

    if not dates:
        log.warning(f"No date directories found in {RAW_DIR} — run collector first.")
        sys.exit(0)

    summaries = []
    for date_str in dates:
        summary = process_day(date_str, overwrite=overwrite)
        summaries.append(summary)

    log.info("\n── Summary ──────────────────────────────────────────")
    for s in summaries:
        log.info(f"  {s['date']}: {s.get('status','?')}  "
                 f"clean={s.get('clean_rows','')}, quarantined={s.get('quarantined','')}")
    log.info("Done.")


if __name__ == "__main__":
    main()
