"""
Parabellum ISOS - Weather Data Service
=================================================================
Collects historical weather for Lipa City, Batangas from Open-Meteo's
free Historical Weather API and syncs monthly aggregates into the
`monthly_weather` table (D8).
"""

from __future__ import annotations
import sys
from datetime import date
import pandas as pd
import requests

from mlr_model import execute_query, _bulk_insert, log_audit

LOCATION_NAME = "Lipa City, Batangas, PH"
LATITUDE = 13.9411
LONGITUDE = 121.1622
TIMEZONE = "Asia/Manila"

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
DEFAULT_START_DATE = "2024-01-01"

DAILY_VARS = ["temperature_2m_mean", "precipitation_sum", "rain_sum", "wind_speed_10m_max"]
RAINY_DAY_THRESHOLD_MM = 1.0
REQUEST_TIMEOUT_SECONDS = 30


def fetch_daily_weather(start_date=DEFAULT_START_DATE, end_date=None,
                        latitude=LATITUDE, longitude=LONGITUDE, timezone=TIMEZONE):
    if end_date is None:
        end_date = date.today().isoformat()
    params = {
        "latitude": latitude, "longitude": longitude,
        "start_date": start_date, "end_date": end_date,
        "daily": ",".join(DAILY_VARS), "timezone": timezone,
    }
    resp = requests.get(ARCHIVE_URL, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    payload = resp.json()
    if "daily" not in payload:
        raise ValueError(f"Open-Meteo response had no 'daily' block: {payload.get('reason', payload)}")
    daily = payload["daily"]
    return pd.DataFrame({
        "date":          pd.to_datetime(daily["time"]),
        "temp_mean_c":   daily.get("temperature_2m_mean"),
        "precip_sum_mm": daily.get("precipitation_sum"),
        "rain_sum_mm":   daily.get("rain_sum"),
        "wind_max_kmh":  daily.get("wind_speed_10m_max"),
    })


def aggregate_monthly(daily_df):
    if daily_df.empty:
        return pd.DataFrame(columns=["period_month", "avg_temp_c", "total_rainfall_mm",
                                     "rainy_days", "max_wind_kmh"])
    df = daily_df.copy()
    df["period_month"] = df["date"].values.astype("datetime64[M]")
    grouped = df.groupby("period_month").agg(
        avg_temp_c=("temp_mean_c", "mean"),
        total_rainfall_mm=("rain_sum_mm", "sum"),
        rainy_days=("rain_sum_mm", lambda s: int((s >= RAINY_DAY_THRESHOLD_MM).sum())),
        max_wind_kmh=("wind_max_kmh", "max"),
    ).reset_index()
    grouped["avg_temp_c"] = grouped["avg_temp_c"].round(2)
    grouped["total_rainfall_mm"] = grouped["total_rainfall_mm"].round(2)
    grouped["max_wind_kmh"] = grouped["max_wind_kmh"].round(2)
    return grouped


def sync_weather_to_db(db_config, start_date=DEFAULT_START_DATE, end_date=None,
                       location_name=LOCATION_NAME, username="system"):
    daily_df = fetch_daily_weather(start_date=start_date, end_date=end_date)
    monthly_df = aggregate_monthly(daily_df)
    if monthly_df.empty:
        raise ValueError("Open-Meteo returned no weather rows for that date range.")

    rows = [(r["period_month"].date(), location_name,
             None if pd.isna(r["avg_temp_c"]) else float(r["avg_temp_c"]),
             None if pd.isna(r["total_rainfall_mm"]) else float(r["total_rainfall_mm"]),
             int(r["rainy_days"]),
             None if pd.isna(r["max_wind_kmh"]) else float(r["max_wind_kmh"]))
            for _, r in monthly_df.iterrows()]

    _bulk_insert(db_config,
        """INSERT INTO monthly_weather
             (period_month, location, avg_temp_c, total_rainfall_mm,
              rainy_days, max_wind_kmh)
           VALUES %s
           ON CONFLICT (period_month, location) DO UPDATE SET
             avg_temp_c        = EXCLUDED.avg_temp_c,
             total_rainfall_mm = EXCLUDED.total_rainfall_mm,
             rainy_days        = EXCLUDED.rainy_days,
             max_wind_kmh      = EXCLUDED.max_wind_kmh,
             fetched_at        = CURRENT_TIMESTAMP;""", rows)

    log_audit(db_config, "SYNC_WEATHER",
        f"Synced {len(rows)} months of weather for {location_name} "
        f"({start_date} to {end_date or date.today().isoformat()}).", username)
    return len(rows)


if __name__ == "__main__":
    from config import DB_CONFIG
    start = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_START_DATE
    end = sys.argv[2] if len(sys.argv) > 2 else None
    print(f"Syncing weather for {LOCATION_NAME} from {start} to {end or 'today'}...")
    n = sync_weather_to_db(DB_CONFIG, start_date=start, end_date=end)
    print(f"Done -- wrote {n} monthly rows to monthly_weather.")
