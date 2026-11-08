"""
etl/static_to_silver.py
─────────────────────────
Converts raw static GTFS .txt files → cleaned Silver Parquet.

Transformations:
  - routes   : select useful columns, add loaded_at
  - trips    : parse trip_id -> route_id + scheduled_HH + scheduled_MM
  - stops    : validate Delhi bbox, flag outliers
  - stop_times: normalize 24:xx arrival/departure times, sort
  - shapes   : pass through (used for maps)

Usage:
    python etl/static_to_silver.py

Output: data/silver/static/  (*.parquet)
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, date, timedelta

import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT      = Path(__file__).resolve().parent.parent
GTFS_DIR  = ROOT / "data" / "static_gtfs"
SILVER    = ROOT / "data" / "silver" / "static"
SILVER.mkdir(parents=True, exist_ok=True)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("static_to_silver")

# Delhi bounding box (rough)
DELHI_LAT_MIN, DELHI_LAT_MAX = 28.40, 28.90
DELHI_LON_MIN, DELHI_LON_MAX = 76.80, 77.40


# ── Helpers ───────────────────────────────────────────────────────────────────
def _read(filename: str) -> pd.DataFrame:
    """Try .txt then .csv."""
    for ext in [".txt", ".csv", ""]:
        p = GTFS_DIR / (filename + ext)
        if p.exists():
            log.info(f"Reading {p.name} ...")
            return pd.read_csv(p, dtype=str, low_memory=False)
    raise FileNotFoundError(f"{filename} not found in {GTFS_DIR}")


def _save(df: pd.DataFrame, name: str):
    out = SILVER / f"{name}.parquet"
    df.to_parquet(out, index=False, engine="pyarrow")
    log.info(f"  → Saved {out.name}  ({len(df):,} rows)")


# ── Per-file processors ───────────────────────────────────────────────────────
def process_routes():
    df = _read("routes")
    df = df[["agency_id", "route_id", "route_short_name",
             "route_long_name", "route_type"]].copy()
    df["loaded_at"] = datetime.utcnow().isoformat()
    _save(df, "routes")
    return df


def process_trips():
    df = _read("trips")
    # Parse trip_id: format is <route_id>_<H>_<M>  (H/M may be 1 or 2 digits)
    parts = df["trip_id"].str.split("_", n=2, expand=True)
    df["sched_route_id"] = parts[0]
    df["sched_HH"] = pd.to_numeric(parts[1], errors="coerce")
    df["sched_MM"] = pd.to_numeric(parts[2], errors="coerce")
    # Normalise minutes field for single-digit minutes that live feed sends
    _save(df, "trips")
    return df


def process_stops():
    df = _read("stops")
    df["stop_lat"] = pd.to_numeric(df["stop_lat"], errors="coerce")
    df["stop_lon"] = pd.to_numeric(df["stop_lon"], errors="coerce")
    # Flag stops outside Delhi bbox
    df["out_of_bbox"] = ~(
        df["stop_lat"].between(DELHI_LAT_MIN, DELHI_LAT_MAX) &
        df["stop_lon"].between(DELHI_LON_MIN, DELHI_LON_MAX)
    )
    n_bad = df["out_of_bbox"].sum()
    if n_bad:
        log.warning(f"  {n_bad} stops outside Delhi bbox — flagged, not removed")
    _save(df, "stops")
    return df


def _normalize_time(t: str) -> tuple[str, int]:
    """
    Normalize GTFS time strings that may have HH >= 24.
    Returns (normalized_time_str, extra_days).
    E.g. '25:30:00' -> ('01:30:00', 1)
    """
    if pd.isna(t) or not isinstance(t, str):
        return t, 0
    parts = t.strip().split(":")
    if len(parts) != 3:
        return t, 0
    hh = int(parts[0])
    extra_days = hh // 24
    hh_norm = hh % 24
    return f"{hh_norm:02d}:{parts[1]}:{parts[2]}", extra_days


def process_stop_times():
    log.info("Reading stop_times (large file, may take ~15s) ...")
    df = _read("stop_times")

    log.info("  Normalizing 24:xx arrival/departure times ...")
    arr_norm, arr_days = zip(*df["arrival_time"].map(_normalize_time))
    dep_norm, dep_days = zip(*df["departure_time"].map(_normalize_time))

    df["arrival_time_norm"]    = arr_norm
    df["departure_time_norm"]  = dep_norm
    df["arrival_day_offset"]   = arr_days
    df["departure_day_offset"] = dep_days

    n24 = sum(1 for d in arr_days if d > 0)
    log.info(f"  Rows with 24:xx normalized: {n24:,}")

    # Ensure numeric stop_sequence for sorting
    df["stop_sequence"] = pd.to_numeric(df["stop_sequence"], errors="coerce")
    df = df.sort_values(["trip_id", "stop_sequence"])
    _save(df, "stop_times")
    return df


def process_shapes():
    df = _read("shapes")
    df["shape_pt_lat"]     = pd.to_numeric(df["shape_pt_lat"], errors="coerce")
    df["shape_pt_lon"]     = pd.to_numeric(df["shape_pt_lon"], errors="coerce")
    df["shape_pt_sequence"] = pd.to_numeric(df["shape_pt_sequence"], errors="coerce")
    _save(df, "shapes")
    return df


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("TRACE — Static GTFS → Silver Parquet")
    log.info("=" * 60)
    t0 = datetime.utcnow()

    process_routes()
    process_trips()
    process_stops()
    process_stop_times()
    process_shapes()

    elapsed = (datetime.utcnow() - t0).total_seconds()
    log.info(f"\nDone in {elapsed:.1f}s — Parquet files in {SILVER}")


if __name__ == "__main__":
    main()
