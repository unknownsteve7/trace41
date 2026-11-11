import os
import sys
import logging
from pathlib import Path
import pandas as pd
import numpy as np
import psycopg
from sklearn.ensemble import RandomForestRegressor, RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, accuracy_score, classification_report, confusion_matrix
from dotenv import load_dotenv
load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'data' / 'ml'
OUT_DIR.mkdir(parents=True, exist_ok=True)
PG_DSN = f"host={os.getenv('PG_HOST', 'localhost')} port={os.getenv('PG_PORT', '5432')} dbname={os.getenv('PG_DATABASE', 'trace_db')} user={os.getenv('PG_USER', 'postgres')} password={os.getenv('PG_PASSWORD', 'trace_pass')}"
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
log = logging.getLogger('delay_prediction')
SEP = '=' * 60

def load_features(conn) -> pd.DataFrame:
    q = '\n    SELECT\n        fa.id,\n        fa.trip_id,\n        dr.route_id,\n        fa.delay_minutes,\n        fa.is_on_time,\n        EXTRACT(HOUR  FROM fa.actual_departure)::INT  AS hour_ist,\n        dd.day_of_week,\n        dd.is_weekend::INT                            AS is_weekend,\n        dd.is_holiday::INT                            AS is_holiday,\n        COALESCE(fw.precipitation_mm, 0)              AS precipitation_mm,\n        COALESCE(fw.is_rainy, FALSE)::INT             AS is_rainy,\n        fa.headway_min,\n        fa.ping_count\n    FROM fact_trip_actual fa\n    JOIN dim_route dr ON dr.route_key = fa.route_key\n    JOIN dim_date  dd ON dd.date_id   = fa.date_id\n    LEFT JOIN fact_weather_daily fw ON fw.date_id = fa.date_id\n    WHERE fa.delay_minutes IS NOT NULL\n      AND fa.actual_departure IS NOT NULL\n    '
    with conn.cursor() as cur:
        cur.execute(q)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description]
    return pd.DataFrame(rows, columns=cols)

def main():
    print(SEP)
    print('  TRACE — ML Delay Prediction (Proof-of-Concept)')
    print('  NOTE: ~4-day pilot dataset. For production use 30+ days.')
    print(SEP)
    with psycopg.connect(PG_DSN) as conn:
        df = load_features(conn)
    if df.empty:
        print('No data yet — run load_facts.py actual first.')
        sys.exit(0)
    print(f'\nLoaded {len(df):,} trip rows with delay labels')
    print(f"Routes: {df['route_id'].nunique()}")
    print(f'Date range: based on joined dim_date')
    print(f"Target distribution (delay_minutes):\n{df['delay_minutes'].describe().round(2)}\n")
    le = LabelEncoder()
    df['route_encoded'] = le.fit_transform(df['route_id'].fillna('unknown'))
    FEATURES = ['hour_ist', 'day_of_week', 'is_weekend', 'is_holiday', 'precipitation_mm', 'is_rainy', 'route_encoded', 'headway_min', 'ping_count']
    df_model = df[FEATURES + ['delay_minutes', 'is_on_time']].dropna()
    print(f'Rows after dropping NaN in features: {len(df_model):,}')
    if len(df_model) < 20:
        print('Too few rows for meaningful ML. Collect more data first.')
        sys.exit(0)
    X = df_model[FEATURES]
    y_reg = df_model['delay_minutes']
    y_cls = df_model['is_on_time'].astype(int)
    test_size = max(0.2, min(0.3, 50 / len(df_model)))
    X_train, X_test, yr_train, yr_test, yc_train, yc_test = train_test_split(X, y_reg, y_cls, test_size=test_size, random_state=42)
    print(f'Train: {len(X_train)}, Test: {len(X_test)}')
    print(f'\n{SEP}')
    print('  REGRESSION: Predicting delay_minutes')
    print(SEP)
    rf_reg = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    rf_reg.fit(X_train, yr_train)
    yr_pred = rf_reg.predict(X_test)
    mae = mean_absolute_error(yr_test, yr_pred)
    rmse = root_mean_squared_error(yr_test, yr_pred)
    print(f'  MAE  = {mae:.2f} minutes')
    print(f'  RMSE = {rmse:.2f} minutes')
    print(f'  Baseline MAE (predict mean) = {mean_absolute_error(yr_test, [yr_train.mean()] * len(yr_test)):.2f} min')
    fi = pd.Series(rf_reg.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print(f'\n  Feature Importance (Regression):')
    for feat, imp in fi.items():
        bar = '#' * int(imp * 50)
        print(f'    {feat:<20} {imp:.4f}  {bar}')
    print(f'\n{SEP}')
    print('  CLASSIFICATION: Predicting is_on_time (delay <= 5 min)')
    print(SEP)
    rf_cls = RandomForestClassifier(n_estimators=100, random_state=42, n_jobs=-1)
    rf_cls.fit(X_train, yc_train)
    yc_pred = rf_cls.predict(X_test)
    acc = accuracy_score(yc_test, yc_pred)
    print(f'  Accuracy = {acc:.3f}')
    print(f'\n  Classification Report:')
    print(classification_report(yc_test, yc_pred, target_names=['Late', 'On-Time']))
    print(f'  Confusion Matrix:')
    print(confusion_matrix(yc_test, yc_pred))
    fi_cls = pd.Series(rf_cls.feature_importances_, index=FEATURES).sort_values(ascending=False)
    print(f'\n  Feature Importance (Classification):')
    for feat, imp in fi_cls.items():
        bar = '#' * int(imp * 50)
        print(f'    {feat:<20} {imp:.4f}  {bar}')
    preds_df = pd.DataFrame({'actual_delay': yr_test.values, 'predicted_delay': yr_pred, 'actual_on_time': yc_test.values, 'pred_on_time': yc_pred})
    preds_df.to_csv(OUT_DIR / 'predictions.csv', index=False)
    metrics_df = pd.DataFrame([{'mae_minutes': round(mae, 2), 'rmse_minutes': round(rmse, 2), 'accuracy': round(acc, 3), 'n_train': len(X_train), 'n_test': len(X_test), 'n_features': len(FEATURES), 'note': 'Pilot model, ~4-day data window'}])
    metrics_df.to_csv(OUT_DIR / 'model_metrics.csv', index=False)
    fi.to_frame('importance_reg').join(fi_cls.to_frame('importance_cls')).reset_index().rename(columns={'index': 'feature'}).to_csv(OUT_DIR / 'feature_importance.csv', index=False)
    print(f'\nOutputs saved to data/ml/')
    print('  predictions.csv       — for Power BI scatter plot')
    print('  model_metrics.csv     — MAE, RMSE, accuracy')
    print('  feature_importance.csv — for Power BI bar chart')
    print(f'\n{SEP}')
    print('  IMPORTANT: This is a proof-of-concept model.')
    print('  Production deployment would need 30+ days of data.')
    print('  Current window: ~4 days (pilot study).')
    print(SEP)
if __name__ == '__main__':
    main()
