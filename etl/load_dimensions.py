import sys
import logging
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import psycopg
from dotenv import load_dotenv
import os
try:
    import holidays
except ImportError:
    holidays = None
load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
SILVER = ROOT / 'data' / 'silver' / 'static'
PG_DSN = f"host={os.getenv('PG_HOST', 'localhost')} port={os.getenv('PG_PORT', '5432')} dbname={os.getenv('PG_DATABASE', 'trace_db')} user={os.getenv('PG_USER', 'postgres')} password={os.getenv('PG_PASSWORD', 'trace_pass')}"
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger('load_dimensions')
DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

def load_dim_date(conn):
    log.info('Loading dim_date (2026-01-01 → 2026-12-31) ...')
    india_holidays = {}
    if holidays:
        try:
            india_holidays = holidays.India(years=2026)
        except Exception:
            log.warning('  holidays package error — is_holiday will be FALSE for all')
    rows = []
    d = date(2026, 1, 1)
    while d <= date(2026, 12, 31):
        dow = d.weekday()
        is_hol = d in india_holidays
        hol_name = india_holidays.get(d, None)
        rows.append((d, d.year, d.month, d.day, dow, DAY_NAMES[dow], d.isocalendar()[1], dow >= 5, is_hol, hol_name))
        d += timedelta(days=1)
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO dim_date\n               (full_date,year,month,day_of_month,day_of_week,day_name,\n                week_of_year,is_weekend,is_holiday,holiday_name)\n               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)\n               ON CONFLICT (full_date) DO NOTHING', rows)
    conn.commit()
    log.info(f'  Inserted/skipped {len(rows)} date rows.')

def load_dim_route(conn):
    p = SILVER / 'routes.parquet'
    if not p.exists():
        log.error(f'  {p} not found — run static_to_silver.py first')
        return
    df = pd.read_parquet(p)
    log.info(f'Loading dim_route: {len(df):,} routes ...')
    rows = [(str(r.get('route_id', '')), str(r.get('route_short_name', ''))[:50] if pd.notna(r.get('route_short_name')) else None, str(r.get('route_long_name', ''))[:255] if pd.notna(r.get('route_long_name')) else None, str(r.get('agency_id', ''))[:20] if pd.notna(r.get('agency_id')) else None, int(r['route_type']) if pd.notna(r.get('route_type')) else 3) for _, r in df.iterrows()]
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO dim_route\n               (route_id, route_short_name, route_long_name, agency_id, route_type)\n               VALUES (%s,%s,%s,%s,%s)\n               ON CONFLICT DO NOTHING', rows)
    conn.commit()
    log.info(f'  Inserted {len(rows)} route rows.')

def load_dim_stop(conn):
    p = SILVER / 'stops.parquet'
    if not p.exists():
        log.error(f'  {p} not found — run static_to_silver.py first')
        return
    df = pd.read_parquet(p)
    log.info(f'Loading dim_stop: {len(df):,} stops ...')
    rows = [(str(r['stop_id']), str(r.get('stop_name', ''))[:200] if pd.notna(r.get('stop_name')) else None, float(r['stop_lat']) if pd.notna(r.get('stop_lat')) else None, float(r['stop_lon']) if pd.notna(r.get('stop_lon')) else None) for _, r in df.iterrows()]
    with conn.cursor() as cur:
        cur.executemany('INSERT INTO dim_stop (stop_id, stop_name, lat, lon)\n               VALUES (%s,%s,%s,%s)\n               ON CONFLICT (stop_id) DO NOTHING', rows)
    conn.commit()
    log.info(f'  Inserted {len(rows)} stop rows.')

def main():
    log.info('=' * 60)
    log.info('TRACE — Load Dimensions → PostgreSQL')
    log.info('=' * 60)
    with psycopg.connect(PG_DSN) as conn:
        load_dim_date(conn)
        load_dim_route(conn)
        load_dim_stop(conn)
    log.info('All dimensions loaded ')
if __name__ == '__main__':
    main()
