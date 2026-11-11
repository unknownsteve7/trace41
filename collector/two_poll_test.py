import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
import requests
from dotenv import load_dotenv
from google.transit import gtfs_realtime_pb2
load_dotenv()
API_KEY = os.getenv('OTD_API_KEY', '')
FEED_URL = os.getenv('OTD_VEHICLE_POSITIONS_URL', 'https://otd.delhi.gov.in/api/realtime/VehiclePositions.pb')
GAP_SECONDS = 30
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('two_poll_test')

def fetch_feed(api_key: str, url: str) -> gtfs_realtime_pb2.FeedMessage:
    params = {'key': api_key} if api_key else {}
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(resp.content)
    return feed

def extract_vehicles(feed: gtfs_realtime_pb2.FeedMessage) -> dict:
    vehicles = {}
    now_utc = int(datetime.now(timezone.utc).timestamp())
    for entity in feed.entity:
        if not entity.HasField('vehicle'):
            continue
        v = entity.vehicle
        vid = v.vehicle.id or entity.id
        ts = v.timestamp or 0
        vehicles[vid] = {'timestamp': ts, 'age_seconds': now_utc - ts if ts else None}
    return vehicles

def run_test():
    if not API_KEY:
        log.warning('OTD_API_KEY not set in .env — attempting without key')
    log.info('=== TRACE Two-Poll Test ===')
    log.info(f'Fetching Poll 1 from {FEED_URL}')
    t0 = datetime.now(timezone.utc)
    feed1 = fetch_feed(API_KEY, FEED_URL)
    poll1 = extract_vehicles(feed1)
    log.info(f'Poll 1: {len(poll1)} vehicles at {t0.isoformat()}')
    log.info(f'Waiting {GAP_SECONDS}s for Poll 2...')
    time.sleep(GAP_SECONDS)
    log.info('Fetching Poll 2')
    t1 = datetime.now(timezone.utc)
    feed2 = fetch_feed(API_KEY, FEED_URL)
    poll2 = extract_vehicles(feed2)
    log.info(f'Poll 2: {len(poll2)} vehicles at {t1.isoformat()}')
    common = set(poll1.keys()) & set(poll2.keys())
    changed = sum((1 for vid in common if poll1[vid]['timestamp'] != poll2[vid]['timestamp']))
    pct_changed = 100.0 * changed / len(common) if common else 0.0
    ages1 = [v['age_seconds'] for v in poll1.values() if v['age_seconds'] is not None]
    ages2 = [v['age_seconds'] for v in poll2.values() if v['age_seconds'] is not None]
    all_ages = ages1 + ages2
    median_age = sorted(all_ages)[len(all_ages) // 2] if all_ages else None
    p95_age = sorted(all_ages)[int(len(all_ages) * 0.95)] if all_ages else None
    print('\n' + '=' * 55)
    print('  TRACE TWO-POLL TEST RESULTS')
    print('=' * 55)
    print(f'  Vehicles in Poll 1       : {len(poll1)}')
    print(f'  Vehicles in Poll 2       : {len(poll2)}')
    print(f'  Common vehicle_ids       : {len(common)}')
    print(f'  Changed timestamp        : {changed} / {len(common)}  ({pct_changed:.1f}%)')
    print(f'  Median position age (s)  : {median_age}')
    print(f'  P95 position age (s)     : {p95_age}')
    print('-' * 55)
    if pct_changed >= 40:
        recommendation = '30s interval  (>= 40% vehicles update each poll)'
    else:
        recommendation = '60s interval  (< 40% update — 30s wastes bandwidth)'
    print(f'  RECOMMENDATION           : {recommendation}')
    print('=' * 55 + '\n')
    print('Set POLL_INTERVAL_SECONDS in .env accordingly.')
if __name__ == '__main__':
    run_test()
