"""
etl/ingest_feedback_api.py
───────────────────────────────────────────────────────────────────────────────
TRACE Pipeline — Automated API Ingestion of Passenger Grievances (Pillar 3).

Connects to the published FastAPI Feedback Service via REST API:
  GET {FEEDBACK_API_URL}/admin/export?since={watermark}&limit=2000
  Header: X-API-KEY: {FEEDBACK_ADMIN_KEY}

Medallion Architecture Flow:
  1. API Ingestion  → data/bronze/complaints/bronze_{timestamp}.json
  2. Silver Layer   → Dedupe, text sanitization, route/vehicle checks → data/silver/complaints.parquet
  3. Gold Star Schema → PostgreSQL fact_complaints (linked to dim_route & dim_date)

Usage:
    python etl/ingest_feedback_api.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
import requests
import pandas as pd
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

BRONZE_DIR = ROOT / "data" / "bronze" / "complaints"
SILVER_DIR = ROOT / "data" / "silver"
WATERMARK_FILE = BRONZE_DIR / "watermark.txt"

BRONZE_DIR.mkdir(parents=True, exist_ok=True)
SILVER_DIR.mkdir(parents=True, exist_ok=True)

FEEDBACK_API_URL = os.getenv("FEEDBACK_API_URL", "http://localhost:8000").rstrip("/")
FEEDBACK_ADMIN_KEY = os.getenv("FEEDBACK_ADMIN_KEY", "trace_admin_secret_key_change_in_prod")

sslmode = os.getenv("PG_SSLMODE", "")
ssl_param = f" sslmode={sslmode}" if sslmode else ""
PG_DSN = (
    f"host={os.getenv('PG_HOST', 'localhost')} "
    f"port={os.getenv('PG_PORT', '5432')} "
    f"dbname={os.getenv('PG_DATABASE', 'trace_db')} "
    f"user={os.getenv('PG_USER', 'postgres')} "
    f"password={os.getenv('PG_PASSWORD', 'trace_pass')}"
    + ssl_param
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("ingest_feedback_api")

def get_last_watermark() -> str | None:
    if WATERMARK_FILE.exists():
        wm = WATERMARK_FILE.read_text(encoding="utf-8").strip()
        return wm if wm else None
    return None

def set_last_watermark(wm: str):
    WATERMARK_FILE.write_text(wm, encoding="utf-8")

def pull_from_api(since: str | None = None) -> list[dict]:
    url = f"{FEEDBACK_API_URL}/admin/export"
    params = {"limit": 2000, "include_synthetic": True}
    if since:
        params["since"] = since

    headers = {"X-API-KEY": FEEDBACK_ADMIN_KEY}

    log.info(f"Connecting to FastAPI Feedback Service: {url} ...")
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        log.info(f"Successfully fetched {len(data)} grievance records from API.")
        return data
    except requests.exceptions.RequestException as e:
        log.error(f"Failed to fetch grievances from FastAPI API: {e}")
        return []

def save_to_bronze(records: list[dict]):
    if not records:
        return
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_file = BRONZE_DIR / f"bronze_{ts}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)
    log.info(f"Saved Bronze snapshot: {out_file.name}")

def transform_to_silver(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    
    # 1. Deduplication
    df = df.drop_duplicates(subset=["feedback_id"])

    # 2. Timestamp normalization
    df["received_at_utc"] = pd.to_datetime(df["received_at_utc"], utc=True)
    df["date_str"] = df["received_at_utc"].dt.strftime("%Y-%m-%d")

    # 3. Clean comment text & ratings
    df["comment"] = df["comment"].fillna("").astype(str).str.strip()
    df["rating"] = pd.to_numeric(df["rating"], errors="coerce").fillna(3).astype(int)

    # 4. Save to Silver Parquet
    silver_path = SILVER_DIR / "complaints.parquet"
    if silver_path.exists():
        existing_df = pd.read_parquet(silver_path)
        combined_df = pd.concat([existing_df, df]).drop_duplicates(subset=["feedback_id"])
    else:
        combined_df = df

    combined_df.to_parquet(silver_path, index=False)
    log.info(f"Updated Silver complaints: {silver_path.name} ({len(combined_df):,} total rows)")
    return df

def load_to_gold(df: pd.DataFrame):
    if df.empty:
        log.info("No new records to load into Gold layer.")
        return

    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            # 1. Build route_id -> route_key map
            cur.execute("SELECT route_id, route_key FROM dim_route WHERE is_current = TRUE;")
            route_map = {str(row[0]): row[1] for row in cur.fetchall()}

            # 2. Build full_date -> date_id map
            cur.execute("SELECT full_date::text, date_id FROM dim_date;")
            date_map = {str(row[0]): row[1] for row in cur.fetchall()}

            insert_rows = []
            for _, r in df.iterrows():
                route_key = route_map.get(str(r["route_id"]))
                date_id   = date_map.get(str(r["date_str"]))
                comment_val = r["comment"] if r["comment"] else f"Rating: {r['rating']}/5 for {r['category']}"

                insert_rows.append((
                    str(r["feedback_id"]),
                    route_key,
                    date_id,
                    None,                       # stop_id
                    str(r["vehicle_id"]),
                    str(r["category"]),
                    comment_val,
                    r["received_at_utc"].to_pydatetime(),
                    bool(r["is_synthetic"])
                ))

            cur.executemany("""
                INSERT INTO fact_complaints
                    (complaint_id, route_key, date_id, stop_id, vehicle_id,
                     category, complaint_text, submitted_at, is_simulated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (complaint_id) DO NOTHING;
            """, insert_rows)

            conn.commit()

            cur.execute("SELECT COUNT(*) FROM fact_complaints;")
            total = cur.fetchone()[0]
            log.info(f"Loaded {len(insert_rows)} rows into fact_complaints. Total Gold records: {total:,}")

def main():
    log.info("=" * 60)
    log.info("TRACE Pipeline — Ingest Grievances via FastAPI Endpoint")
    log.info("=" * 60)

    watermark = get_last_watermark()
    if watermark:
        log.info(f"Incremental pull using watermark: {watermark}")
    else:
        log.info("Initial full pull (no previous watermark)")

    records = pull_from_api(since=watermark)
    if not records:
        log.info("No new records returned by API.")
        return

    # Bronze
    save_to_bronze(records)

    # Silver
    df_clean = transform_to_silver(records)

    # Gold
    load_to_gold(df_clean)

    # Advance Watermark
    max_ts = max(r["received_at_utc"] for r in records)
    set_last_watermark(str(max_ts))
    log.info(f"Advanced watermark to: {max_ts}")
    log.info("Pipeline sync completed successfully [OK]")

if __name__ == "__main__":
    main()
