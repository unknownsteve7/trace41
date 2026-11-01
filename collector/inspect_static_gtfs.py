"""
collector/inspect_static_gtfs.py
─────────────────────────────────
Day 1 static GTFS check.

Reads from data/static_gtfs/ (unzipped).
Prints:
  1. agency.txt  — name, timezone, URL
  2. calendar.txt — date range coverage
  3. Route/trip/stop counts
  4. stop_times.txt — row count, file size, 24+ hour times
  5. LIVE MATCH TEST — fetches one live poll, checks what % of
     live trip_ids and route_ids exist in static GTFS

Usage:
    python collector/inspect_static_gtfs.py

Set GTFS_DIR in .env or it defaults to data/static_gtfs/
"""

import os
import sys
import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2

load_dotenv()

GTFS_DIR = Path(os.getenv("STATIC_GTFS_PATH", "data/static_gtfs"))
API_KEY  = os.getenv("OTD_API_KEY", "")
FEED_URL = os.getenv(
    "OTD_VEHICLE_POSITIONS_URL",
    "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("inspect_gtfs")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve(filename: str) -> Path | None:
    """Try both .txt and .csv variants."""
    for ext in ["", ".csv", ".txt"]:
        # filename may already have extension
        stem = filename.replace(".txt", "").replace(".csv", "")
        for candidate in [stem + ext, filename]:
            p = GTFS_DIR / candidate
            if p.exists():
                return p
    return None


def read_csv(filename: str) -> list[dict]:
    p = _resolve(filename)
    if p is None:
        log.warning(f"  {filename} (or .csv/.txt) NOT FOUND in {GTFS_DIR}")
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def count_rows_fast(filename: str) -> tuple[int, float]:
    """Returns (row_count, file_size_MB). Counts lines, not full parse."""
    p = _resolve(filename)
    if p is None:
        return 0, 0.0
    size_mb = p.stat().st_size / 1_048_576
    with open(p, "rb") as f:
        count = sum(1 for _ in f) - 1   # subtract header
    return count, size_mb


def check_24plus_times(filename: str, col: str = "arrival_time") -> int:
    """Count rows in stop_times where arrival_time >= 24:00:00"""
    p = _resolve(filename)
    if p is None:
        return 0
    count = 0
    with open(p, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            t = row.get(col, "")
            if t and t.strip() and int(t.split(":")[0]) >= 24:
                count += 1
    return count


# ── Sections ──────────────────────────────────────────────────────────────────

def check_agency():
    print("\n── 1. AGENCY ────────────────────────────────────")
    rows = read_csv("agency.txt")
    for r in rows:
        print(f"  agency_name     : {r.get('agency_name','?')}")
        print(f"  agency_timezone : {r.get('agency_timezone','?')}")
        print(f"  agency_url      : {r.get('agency_url','?')}")


def check_calendar():
    print("\n── 2. CALENDAR COVERAGE ─────────────────────────")
    rows = read_csv("calendar.txt")
    if rows:
        dates = [r.get("start_date","") for r in rows] + [r.get("end_date","") for r in rows]
        dates = [d for d in dates if d]
        print(f"  calendar.txt rows  : {len(rows)}")
        print(f"  Earliest start_date: {min(dates)}")
        print(f"  Latest end_date    : {max(dates)}")
        today = date.today().strftime("%Y%m%d")
        expired = all(d < today for d in [r.get("end_date","") for r in rows])
        status = "EXPIRED (stale snapshot)" if expired else "ACTIVE or partially active"
        print(f"  Coverage vs today  : {status}")
    
    dates_rows = read_csv("calendar_dates.txt")
    if dates_rows:
        exc_types = {}
        for r in dates_rows:
            t = r.get("exception_type","?")
            exc_types[t] = exc_types.get(t, 0) + 1
        print(f"  calendar_dates.txt rows : {len(dates_rows)}")
        for k, v in exc_types.items():
            label = "added" if k == "1" else "removed" if k == "2" else k
            print(f"    exception_type {k} ({label}): {v}")


def check_counts():
    print("\n── 3. ENTITY COUNTS ─────────────────────────────")
    for fname, label in [
        ("routes",    "routes"),
        ("trips",     "trips"),
        ("stops",     "stops"),
        ("shapes",    "shape points"),
    ]:
        n, mb = count_rows_fast(fname)
        if n:
            print(f"  {label:<15}: {n:>8,}  ({mb:.1f} MB)")
        else:
            print(f"  {label:<15}: NOT FOUND")

    # stop_times separately — may be huge
    print("\n── 4. STOP_TIMES ────────────────────────────────")
    n, mb = count_rows_fast("stop_times")
    print(f"  Total rows     : {n:>10,}")
    print(f"  File size      : {mb:.1f} MB")
    if mb > 90:
        print(f"  WARNING: OVER 90 MB — confirm .gitignore covers stop_times.csv/txt")

    print("  Counting 24:00+ arrival times (may take ~30s)...")
    n24 = check_24plus_times("stop_times", "arrival_time")
    print(f"  Rows with hour >= 24 (need normalization): {n24:,}")


def check_live_match():
    print("\n── 5. LIVE TRIP_ID / ROUTE_ID MATCH TEST ────────")
    print("  Fetching one live poll from OTD...")

    if not API_KEY:
        print("  WARNING: OTD_API_KEY not set in .env — skipping live match test")
        print("  Add key to .env and re-run to get match %.")
        return

    params = {"key": API_KEY}
    raw_bytes = None
    last_err = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(FEED_URL, params=params, timeout=30, stream=True)
            resp.raise_for_status()
            raw_bytes = b"".join(resp.iter_content(chunk_size=65536))
            break
        except Exception as e:
            last_err = e
            print(f"  Attempt {attempt} failed: {e} — retrying...")
            import time as _time; _time.sleep(2)
    if raw_bytes is None:
        print(f"  Could not fetch live feed after 3 attempts: {last_err}")
        print("  Skipping match test — check API key and network.")
        return

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(raw_bytes)

    live_trip_ids  = set()
    live_route_ids = set()
    for entity in feed.entity:
        if entity.HasField("vehicle"):
            v = entity.vehicle
            if v.trip.trip_id:
                live_trip_ids.add(v.trip.trip_id)
            if v.trip.route_id:
                live_route_ids.add(v.trip.route_id)

    print(f"  Live feed entities         : {len(feed.entity)}")
    print(f"  Unique trip_ids in feed    : {len(live_trip_ids)}")
    print(f"  Unique route_ids in feed   : {len(live_route_ids)}")

    # Load static sets
    trips_rows  = read_csv("trips")
    routes_rows = read_csv("routes")
    static_trip_ids  = {r.get("trip_id","")  for r in trips_rows}
    static_route_ids = {r.get("route_id","") for r in routes_rows}

    # Trip match
    if live_trip_ids:
        matched_trips = live_trip_ids & static_trip_ids
        pct_trip = 100.0 * len(matched_trips) / len(live_trip_ids)
        print(f"\n  trip_id match  : {len(matched_trips)}/{len(live_trip_ids)}"
              f"  = {pct_trip:.1f}%")
        
        # Route match
        matched_routes = live_route_ids & static_route_ids
        pct_route = 100.0 * len(matched_routes) / len(live_route_ids) if live_route_ids else 0
        print(f"  route_id match : {len(matched_routes)}/{len(live_route_ids)}"
              f"  = {pct_route:.1f}%")

        print("\n  ── VERDICT ──────────────────────────────────")
        if pct_trip >= 60:
            print("  ✅ HIGH MATCH  → schedule-vs-actual delay is viable")
            print("     Use Fact_TripSchedule + Fact_TripActual with trip_id join")
        elif pct_trip >= 20:
            print("  ⚠️  MEDIUM MATCH → delay possible for matched subset only")
            print("     Caveat clearly: analysis covers matched trips only")
        else:
            print("  ❌ LOW MATCH   → static GTFS is too stale for trip_id join")
            print("     Use GPS-ONLY KPIs: headway, bunching, speed, dwell time")
            print("     Route geometry (stops lat/lon) still useful for mapping")
    else:
        print("  ⚠️  No trip_ids in live feed — feed may use different fields")
        print("  Sample first 3 entity IDs:", [e.id for e in list(feed.entity)[:3]])

    # Save sample trip_ids for manual inspection
    sample_path = Path("data/sample/live_trip_ids_sample.txt")
    sample_path.parent.mkdir(exist_ok=True)
    with open(sample_path, "w") as f:
        for tid in sorted(live_trip_ids)[:50]:
            f.write(tid + "\n")
    print(f"\n  First 50 live trip_ids saved → {sample_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not GTFS_DIR.exists():
        print(f"ERROR: GTFS_DIR not found: {GTFS_DIR.resolve()}")
        print("Download and unzip mdb-3139 into data/static_gtfs/ first.")
        sys.exit(1)

    print("=" * 55)
    print("  TRACE STATIC GTFS INSPECTION REPORT")
    print(f"  Source: {GTFS_DIR.resolve()}")
    print(f"  Run at: {datetime.now().isoformat()}")
    print("=" * 55)

    check_agency()
    check_calendar()
    check_counts()
    check_live_match()

    print("\n" + "=" * 55)
    print("  Inspection complete. Decisions to record in docs/gtfs_validation_report.md")
    print("=" * 55)


if __name__ == "__main__":
    main()
