"""
collector/poll_gtfs_rt.py
─────────────────────────
Main GTFS-RT polling daemon.

Behaviour:
- Runs only during service hours (SERVICE_START_HOUR to SERVICE_END_HOUR).
- Every POLL_INTERVAL_SECONDS: fetches VehiclePositions.pb, saves raw bytes
  to  data/raw/<YYYY-MM-DD>/<epoch_ms>.pb  (never overwritten).
- Logs every poll to logs/collector.log AND appends a row to
  data/raw/etl_run_log.csv for later ETL tracking.
- On HTTP/network error: exponential backoff (max 5 retries), then logs and
  continues to next scheduled poll — never crashes.
- Laptop must not sleep. Run in a terminal and keep screen on.

Usage:
    python collector/poll_gtfs_rt.py

Stop:  Ctrl+C (writes final log line before exit).
"""

import csv
import os
import sys
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── Config ────────────────────────────────────────────────────────────────────
load_dotenv()

API_KEY       = os.getenv("OTD_API_KEY", "")
FEED_URL      = os.getenv(
    "OTD_VEHICLE_POSITIONS_URL",
    "https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb"
)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_SECONDS", "60"))
SVC_START     = int(os.getenv("SERVICE_START_HOUR", "5"))
SVC_END       = int(os.getenv("SERVICE_END_HOUR", "23"))

RAW_DIR       = Path("data/raw")
RAW_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR       = Path("logs")
RUN_LOG_CSV   = RAW_DIR / "etl_run_log.csv"

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "collector.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("collector")

# ── ETL Run Log CSV ───────────────────────────────────────────────────────────
RUN_LOG_FIELDS = [
    "poll_started_utc", "poll_finished_utc", "output_file",
    "bytes_written", "http_status", "error_message"
]

def _init_run_log():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not RUN_LOG_CSV.exists():
        with open(RUN_LOG_CSV, "w", newline="") as f:
            csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS).writeheader()

def _append_run_log(row: dict):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG_CSV, "a", newline="") as f:
        csv.DictWriter(f, fieldnames=RUN_LOG_FIELDS).writerow(row)


# ── Core fetch with retry ─────────────────────────────────────────────────────
def fetch_with_retry(url: str, api_key: str, max_retries: int = 5) -> bytes | None:
    """
    Fetch raw protobuf bytes. Returns None on permanent failure after retries.
    Implements exponential backoff: 2, 4, 8, 16, 32 seconds.
    """
    params = {"key": api_key} if api_key else {}
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30, stream=True)
            resp.raise_for_status()
            return b"".join(resp.iter_content(chunk_size=65536))
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            log.warning(f"HTTP {status} on attempt {attempt}/{max_retries}: {e}")
            if status in (401, 403):
                log.error("Auth error — check OTD_API_KEY in .env. Skipping poll.")
                return None
        except requests.exceptions.RequestException as e:
            log.warning(f"Network error attempt {attempt}/{max_retries}: {e}")

        if attempt < max_retries:
            sleep = 2 ** attempt
            log.info(f"Backing off {sleep}s before retry...")
            time.sleep(sleep)

    log.error(f"All {max_retries} retries exhausted — skipping this poll.")
    return None


# ── Single poll ───────────────────────────────────────────────────────────────
def do_poll() -> dict:
    """Execute one poll cycle. Returns a run-log row dict."""
    now_utc = datetime.now(timezone.utc)
    epoch_ms = int(now_utc.timestamp() * 1000)
    date_str = now_utc.strftime("%Y-%m-%d")

    out_dir = RAW_DIR / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{epoch_ms}.pb"

    row = {
        "poll_started_utc": now_utc.isoformat(),
        "poll_finished_utc": None,
        "output_file": str(out_file),
        "bytes_written": 0,
        "http_status": "ok",
        "error_message": "",
    }

    raw_bytes = fetch_with_retry(FEED_URL, API_KEY)

    if raw_bytes is None:
        row["http_status"] = "error"
        row["error_message"] = "fetch failed after retries"
        log.error(f"Poll FAILED -> no file written")
    else:
        out_file.write_bytes(raw_bytes)
        row["bytes_written"] = len(raw_bytes)
        log.info(f"Poll OK -> {out_file.name}  ({len(raw_bytes):,} bytes)")

    row["poll_finished_utc"] = datetime.now(timezone.utc).isoformat()
    return row


# ── Service-hour guard ────────────────────────────────────────────────────────
def in_service_hours() -> bool:
    hour = datetime.now().hour
    return SVC_START <= hour < SVC_END


def sleep_until_service():
    """Block until service hours begin, checking every minute."""
    while not in_service_hours():
        now = datetime.now()
        log.info(
            f"Outside service hours ({SVC_START}:00–{SVC_END}:00). "
            f"Current time: {now.strftime('%H:%M')}. Sleeping 60s..."
        )
        time.sleep(60)


import argparse

# ── Main loop ─────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="TRACE GTFS-RT Polling Collector")
    parser.add_argument("--count", type=int, default=0, help="Number of polls to perform (0 = run indefinitely)")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help="Poll interval in seconds")
    args = parser.parse_args()

    poll_int = args.interval
    max_polls = args.count

    if not API_KEY:
        log.warning("OTD_API_KEY not set in .env — requests will be sent without key")

    _init_run_log()
    log.info(f"=== TRACE Collector started ===")
    log.info(f"Feed URL      : {FEED_URL}")
    log.info(f"Poll interval : {poll_int}s")
    log.info(f"Max polls     : {'Unlimited (Daemon)' if max_polls == 0 else max_polls}")
    log.info(f"Service hours : {SVC_START}:00 – {SVC_END}:00")
    log.info(f"Raw output dir: {RAW_DIR.resolve()}")
    log.info(f"Run log CSV   : {RUN_LOG_CSV.resolve()}")
    if max_polls == 0:
        log.info("Press Ctrl+C to stop gracefully.\n")

    polls_done = 0
    try:
        while True:
            sleep_until_service()
            row = do_poll()
            _append_run_log(row)
            polls_done += 1

            if max_polls > 0 and polls_done >= max_polls:
                log.info(f"Reached requested poll limit of {max_polls}. Exiting.")
                break

            # Countdown to next poll
            next_poll = datetime.now()
            log.info(
                f"[Poll #{polls_done}] Next poll in {poll_int}s "
                f"(~{next_poll.strftime('%H:%M:%S')})"
            )
            time.sleep(poll_int)

    except KeyboardInterrupt:
        log.info(f"\n=== Collector stopped by user. Total polls: {polls_done} ===")
        sys.exit(0)


if __name__ == "__main__":
    main()
