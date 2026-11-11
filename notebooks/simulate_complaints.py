import csv
import uuid
import random
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pandas as pd
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'complaints'
OUT.mkdir(parents=True, exist_ok=True)
routes_p = ROOT / 'data' / 'silver' / 'static' / 'routes.parquet'
stops_p = ROOT / 'data' / 'silver' / 'static' / 'stops.parquet'
if routes_p.exists():
    routes_df = pd.read_parquet(routes_p)
    route_ids = routes_df['route_id'].dropna().tolist()[:50]
else:
    route_ids = [str(r) for r in range(1000, 1050)]
if stops_p.exists():
    stops_df = pd.read_parquet(stops_p)
    stop_ids = stops_df['stop_id'].dropna().tolist()[:100]
else:
    stop_ids = [f'DEL{n:04d}' for n in range(1, 101)]
CATEGORIES = ['Late Arrival', 'No Show', 'Overcrowding', 'Wrong Route', 'Driver Behavior', 'Vehicle Breakdown']
CATEGORY_WEIGHTS = [0.35, 0.25, 0.2, 0.08, 0.07, 0.05]
TEXTS = {'Late Arrival': ['Bus was 20 mins late', 'Very delayed today', 'Always late on this route'], 'No Show': ['Bus never came', 'Waited 45 mins, no bus', 'Service completely missing'], 'Overcrowding': ['Too packed to board', "Couldn't get on, too full", 'Need more buses'], 'Wrong Route': ['Driver took wrong road', 'Route sign incorrect'], 'Driver Behavior': ['Rash driving', 'Driver was rude', 'Skipped my stop without stopping'], 'Vehicle Breakdown': ['Bus broke down mid-route', 'Engine problems, had to leave bus']}
random.seed(42)
base_date = datetime(2026, 11, 5, tzinfo=timezone.utc)
rows = []
for _ in range(200):
    route_id = random.choice(route_ids)
    stop_id = random.choice(stop_ids)
    cat = random.choices(CATEGORIES, weights=CATEGORY_WEIGHTS, k=1)[0]
    text = random.choice(TEXTS[cat]) if random.random() > 0.4 else ''
    day_offset = random.randint(0, 3)
    hour = random.choice([7, 8, 9, 10, 17, 18, 19, 20, 12, 13])
    dt = base_date + timedelta(days=day_offset, hours=hour, minutes=random.randint(0, 59))
    rows.append({'complaint_id': str(uuid.uuid4()), 'route_id': route_id, 'stop_id': stop_id, 'vehicle_id': f'DL{random.randint(1, 9)}P{random.randint(1000, 9999)}', 'category': cat, 'complaint_text': text, 'submitted_at': dt.isoformat(), 'date': dt.date().isoformat(), 'is_simulated': True})
out_path = OUT / 'simulated.csv'
with open(out_path, 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
print(f'Generated {len(rows)} simulated complaints -> {out_path}')
from collections import Counter
cats = Counter((r['category'] for r in rows))
for c, n in cats.most_common():
    print(f'  {c:<25}: {n} ({100 * n / len(rows):.0f}%)')
