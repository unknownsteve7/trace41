import os
import sys
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import psycopg
import math
from dotenv import load_dotenv
try:
    from scipy import stats
except ImportError:

    class DummyStats:

        @staticmethod
        def mannwhitneyu(x, y, alternative='two-sided'):
            x = np.asarray(x)
            y = np.asarray(y)
            n1 = len(x)
            n2 = len(y)
            ranked = pd.Series(np.concatenate([x, y])).rank(method='average').values
            r1 = np.sum(ranked[:n1])
            u1 = r1 - n1 * (n1 + 1) / 2
            u2 = n1 * n2 - u1
            u = u1 if alternative != 'greater' else u1
            mu = n1 * n2 / 2
            sigma = math.sqrt(n1 * n2 * (n1 + n2 + 1) / 12)
            z = (u - mu) / sigma if sigma > 0 else 0
            p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
            return (u, max(0.0001, min(1.0, p)))

        @staticmethod
        def kruskal(*args):
            all_vals = np.concatenate(args)
            n_tot = len(all_vals)
            ranked = pd.Series(all_vals).rank(method='average').values
            idx = 0
            h_sum = 0
            for grp in args:
                n_i = len(grp)
                r_i = np.sum(ranked[idx:idx + n_i])
                idx += n_i
                h_sum += r_i ** 2 / n_i
            h = 12 / (n_tot * (n_tot + 1)) * h_sum - 3 * (n_tot + 1)
            df = len(args) - 1
            z = math.sqrt(2 * h) - math.sqrt(2 * df - 1) if h > df else 0
            p = 0.5 * (1 - math.erf(z / math.sqrt(2))) if z > 0 else 0.5
            return (h, max(0.0001, min(1.0, p)))

        @staticmethod
        def spearmanr(x, y):
            x_r = pd.Series(x).rank().values
            y_r = pd.Series(y).rank().values
            n = len(x)
            d2 = np.sum((x_r - y_r) ** 2)
            rho = 1 - 6 * d2 / (n * (n ** 2 - 1)) if n > 1 else 0
            t = rho * math.sqrt((n - 2) / max(0.0001, 1 - rho ** 2)) if abs(rho) < 1 else 10
            p = 2 * (1 - 0.5 * (1 + math.erf(abs(t) / math.sqrt(2))))
            return (rho, max(0.0001, min(1.0, p)))
    stats = DummyStats()
from dotenv import load_dotenv
load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'data' / 'stats'
OUT_DIR.mkdir(parents=True, exist_ok=True)
PG_DSN = f"host={os.getenv('PG_HOST', 'localhost')} port={os.getenv('PG_PORT', '5432')} dbname={os.getenv('PG_DATABASE', 'trace_db')} user={os.getenv('PG_USER', 'postgres')} password={os.getenv('PG_PASSWORD', 'trace_pass')}"
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger('stats_analysis')
SEP = '=' * 60

def load_route_day_agg(conn) -> pd.DataFrame:
    q = '\n    SELECT\n        fa.route_key,\n        dr.route_short_name,\n        dd.full_date,\n        dd.day_of_week,\n        dd.day_name,\n        dd.is_weekend,\n        dd.is_holiday,\n        COALESCE(fw.precipitation_mm, 0)        AS precipitation_mm,\n        COALESCE(fw.is_rainy, FALSE)             AS is_rainy,\n        COUNT(fa.id)                             AS trips_total,\n        COUNT(*) FILTER (WHERE fa.is_on_time)    AS trips_on_time,\n        ROUND(AVG(fa.delay_minutes)::NUMERIC, 4) AS avg_delay_min,\n        ROUND(AVG(fa.headway_min)::NUMERIC, 4)   AS avg_headway_min,\n        SUM(fa.is_bunched::INT)                  AS bunched_count,\n        ROUND(100.0 * SUM(fa.is_bunched::INT)\n              / NULLIF(COUNT(*),0), 4)           AS bunching_rate_pct\n    FROM fact_trip_actual fa\n    JOIN dim_route dr ON dr.route_key = fa.route_key\n    JOIN dim_date  dd ON dd.date_id   = fa.date_id\n    LEFT JOIN fact_weather_daily fw ON fw.date_id = fa.date_id\n    WHERE fa.delay_minutes IS NOT NULL\n    GROUP BY fa.route_key, dr.route_short_name,\n             dd.full_date, dd.day_of_week, dd.day_name,\n             dd.is_weekend, dd.is_holiday,\n             fw.precipitation_mm, fw.is_rainy\n    HAVING COUNT(fa.id) >= 3  -- at least 3 trips observed\n    '
    with conn.cursor() as cur:
        cur.execute(q)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)

def print_result(test_name, stat, p_value, group_a, group_b, conclusion):
    sig = '***' if p_value < 0.001 else '**' if p_value < 0.01 else '*' if p_value < 0.05 else 'ns'
    print(f'\n{SEP}')
    print(f'  TEST: {test_name}')
    print(f'  Group A ({group_a[0]}): n={group_a[1]}, median={group_a[2]:.2f} min')
    print(f'  Group B ({group_b[0]}): n={group_b[1]}, median={group_b[2]:.2f} min')
    print(f'  Statistic = {stat:.4f}   p-value = {p_value:.4f}  {sig}')
    print(f'  CONCLUSION: {conclusion}')
    print(SEP)

def run_tests(df: pd.DataFrame) -> list[dict]:
    results = []
    log.info('Test 1: Peak vs Off-Peak — using route-day delay (approximated by time of day bucket)')
    weekday = df[~df['is_weekend']]['avg_delay_min'].dropna()
    weekend = df[df['is_weekend']]['avg_delay_min'].dropna()
    if len(weekday) >= 3 and len(weekend) >= 3:
        stat, p = stats.mannwhitneyu(weekday, weekend, alternative='two-sided')
        conclusion = 'Weekday delays are significantly higher than weekends (p<0.05).' if p < 0.05 else 'No significant difference between weekday and weekend delay (p>=0.05).'
        print_result('Weekday vs Weekend Avg Delay (Mann-Whitney U)', stat, p, ('Weekday', len(weekday), weekday.median()), ('Weekend', len(weekend), weekend.median()), conclusion)
        results.append({'test': 'weekday_vs_weekend', 'stat': stat, 'p_value': p, 'n_a': len(weekday), 'n_b': len(weekend), 'median_a': weekday.median(), 'median_b': weekend.median(), 'conclusion': conclusion})
    else:
        log.warning('Not enough route-day rows for Weekday/Weekend test (need >= 3 each).')
    rainy = df[df['is_rainy'] == True]['avg_delay_min'].dropna()
    dry = df[df['is_rainy'] == False]['avg_delay_min'].dropna()
    if len(rainy) >= 3 and len(dry) >= 3:
        stat, p = stats.mannwhitneyu(rainy, dry, alternative='greater')
        conclusion = 'Rainy days have significantly higher delays (p<0.05).' if p < 0.05 else 'No significant rain effect on delay detected (p>=0.05) — likely too few rainy days in sample.'
        print_result('Rainy vs Dry Day Delay (Mann-Whitney U, one-sided)', stat, p, ('Rainy', len(rainy), rainy.median()), ('Dry', len(dry), dry.median()), conclusion)
        results.append({'test': 'rainy_vs_dry', 'stat': stat, 'p_value': p, 'n_a': len(rainy), 'n_b': len(dry), 'median_a': rainy.median(), 'median_b': dry.median(), 'conclusion': conclusion})
    else:
        log.warning(f'Only {len(rainy)} rainy route-days in sample — rain test skipped (Plan B: use peak/off-peak).')
        groups = [g['avg_delay_min'].dropna().values for _, g in df.groupby('day_of_week') if len(g) >= 3]
        if len(groups) >= 2:
            stat, p = stats.kruskal(*groups)
            conclusion = 'Significant variation in delay across days of week (p<0.05).' if p < 0.05 else 'No significant variation across days of week (p>=0.05).'
            print(f'\n{SEP}')
            print(f'  TEST: Day-of-week effect on delay (Kruskal-Wallis)')
            print(f'  Groups: {len(groups)} day-of-week levels')
            print(f'  H = {stat:.4f}   p-value = {p:.4f}')
            print(f'  CONCLUSION: {conclusion}')
            print(SEP)
            results.append({'test': 'day_of_week_kruskal', 'stat': stat, 'p_value': p, 'n_a': sum((len(g) for g in groups)), 'n_b': None, 'median_a': None, 'median_b': None, 'conclusion': conclusion})
    corr_df = df[['avg_headway_min', 'bunching_rate_pct']].dropna()
    if len(corr_df) >= 5:
        rho, p = stats.spearmanr(corr_df['avg_headway_min'], corr_df['bunching_rate_pct'])
        conclusion = f"Routes with longer avg headways tend to have {('higher' if rho > 0 else 'lower')} bunching rates (rho={rho:.3f}, {('significant' if p < 0.05 else 'not significant')} at p=0.05)."
        print(f'\n{SEP}')
        print(f'  TEST: Avg Headway vs Bunching Rate (Spearman)')
        print(f'  n = {len(corr_df)}')
        print(f'  rho = {rho:.4f}   p-value = {p:.4f}')
        print(f'  CONCLUSION: {conclusion}')
        print(SEP)
        results.append({'test': 'headway_vs_bunching_spearman', 'stat': rho, 'p_value': p, 'n_a': len(corr_df), 'n_b': None, 'median_a': None, 'median_b': None, 'conclusion': conclusion})
    holiday = df[df['is_holiday'] == True]['avg_delay_min'].dropna()
    non_holiday = df[df['is_holiday'] == False]['avg_delay_min'].dropna()
    if len(holiday) >= 3 and len(non_holiday) >= 3:
        stat, p = stats.mannwhitneyu(non_holiday, holiday, alternative='greater')
        conclusion = 'Non-holiday days have significantly higher delays than holidays (p<0.05).' if p < 0.05 else 'No significant holiday effect on delay (p>=0.05).'
        print_result('Holiday vs Non-Holiday Delay (Mann-Whitney U)', stat, p, ('Non-Holiday', len(non_holiday), non_holiday.median()), ('Holiday', len(holiday), holiday.median()), conclusion)
        results.append({'test': 'holiday_effect', 'stat': stat, 'p_value': p, 'n_a': len(non_holiday), 'n_b': len(holiday), 'median_a': non_holiday.median(), 'median_b': holiday.median(), 'conclusion': conclusion})
    else:
        log.warning(f'Holiday sample size too small (holidays={len(holiday)}) - skipping holiday test.')
    return results

def main():
    print(SEP)
    print('  TRACE — Statistical Analysis')
    print('  Grain: route-day aggregates (NOT raw pings)')
    print(SEP)
    with psycopg.connect(PG_DSN) as conn:
        df = load_route_day_agg(conn)
    print(f'\nLoaded {len(df):,} route-day aggregate rows')
    print(f"Date range: {df['full_date'].min()} to {df['full_date'].max()}")
    print(f"Routes:     {df['route_short_name'].nunique()}")
    print(f"Rainy days: {df[df['is_rainy']]['full_date'].nunique()}")
    if df.empty:
        print('\nNo data yet — run ETL first (load_facts.py actual)')
        sys.exit(0)
    results = run_tests(df)
    if results:
        out = OUT_DIR / 'stat_results.csv'
        pd.DataFrame(results).to_csv(out, index=False)
        print(f'\nResults saved to {out}')
    print(f"\n{'=' * 60}")
    print('  DESCRIPTIVE SUMMARY')
    print(f"{'=' * 60}")
    print(df[['avg_delay_min', 'avg_headway_min', 'bunching_rate_pct']].describe().round(2).to_string())
if __name__ == '__main__':
    main()
