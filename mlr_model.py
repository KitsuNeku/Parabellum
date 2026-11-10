import json

import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from db import execute_query, bulk_insert, log_audit

MODEL_NAME = "Multiple Linear Regression"
NO_WEATHER_NAME = "MLR without weather"
NAIVE_NAME = "Naive (last month)"

LOCATION_NAME = "Lipa City, Batangas, PH"

WEATHER_FEATURES = ["avg_temp_c", "total_rainfall_mm", "rainy_days"]
# prev_year_demand is the demand for the same calendar month 12 months prior.
# Captures the year-over-year seasonal signal directly (e.g. Nov 2026's forecast
# uses Nov 2025 as one of its inputs), on top of the month_sin/month_cos
# encoding of the time of year.
LAG_FEATURES = ["prev_demand", "prev_demand_2", "prev_year_demand"]
SEASON_FEATURES = ["month_sin", "month_cos"]
MODEL_WEATHER = ["total_rainfall_mm", "rainy_days"]
FEATURES = LAG_FEATURES + SEASON_FEATURES + MODEL_WEATHER
FEATURES_NO_WEATHER = LAG_FEATURES + SEASON_FEATURES

MIN_TRAINING_ROWS = 20
MIN_PER_MATERIAL_ROWS = 15
SAMPLE_SIZE_WARN_THRESHOLD = 24
MAX_HOLDOUT_MONTHS = 6
MIN_HOLDOUT_MONTHS = 3
WEATHER_HELPS_THRESHOLD = 2.0

MIN_MOVEMENT_WEATHER_DAYS = 3

def get_materials(db_config):
    rows = execute_query(
        db_config,
        """SELECT material_id, material_code, material_name, unit,
                  unit_cost, current_stock, reorder_level
             FROM materials ORDER BY material_name;""",
        fetch=True,
    )
    return [dict(r) for r in rows]


def get_forecast_history(db_config, limit=15):
    rows = execute_query(
        db_config,
        """SELECT fr.forecast_id, fr.material_id, m.material_name,
                  fr.forecast_month, fr.predicted_demand, fr.generated_at,
                  md.demand_qty AS actual_demand
             FROM forecast_results fr
             JOIN materials m ON m.material_id = fr.material_id
        LEFT JOIN monthly_demand md
                  ON md.material_id = fr.material_id
                 AND md.period_month = fr.forecast_month
            ORDER BY fr.generated_at DESC, fr.forecast_id DESC
            LIMIT %s;""",
        (limit,),
        fetch=True,
    )
    result = []
    for r in rows:
        predicted = float(r["predicted_demand"])
        month_over = (pd.Timestamp(r["forecast_month"]) + pd.offsets.MonthBegin(1)) <= pd.Timestamp.today().normalize()
        actual = float(r["actual_demand"]) if r["actual_demand"] is not None and month_over else None
        accuracy = None
        if actual is not None and actual > 0:
            err_pct = abs(predicted - actual) / actual * 100
            accuracy = round(max(0.0, 100 - err_pct), 1)
        result.append({
            "id":        f"FC-{int(r['forecast_id']):03d}",
            "material":  r["material_name"],
            "month":     r["forecast_month"].strftime("%b %Y"),
            "predicted": round(predicted, 2),
            "actual":    round(actual, 2) if actual is not None else None,
            "accuracy":  accuracy,
        })
    return result


# Weather Favorability Index + insight

def aggregate_monthly_demand(db_config):
    materials = pd.DataFrame(execute_query(
        db_config,
        "SELECT material_id, material_name, unit_cost FROM materials;",
        fetch=True,
    ))
    movements = pd.DataFrame(execute_query(
        db_config,
        "SELECT material_id, movement_type, quantity, movement_date FROM stock_movements "
        "WHERE NOT (movement_type = 'ISSUANCE' AND returned_at IS NOT NULL);",
        fetch=True,
    ))
    if materials.empty or movements.empty:
        raise ValueError("No materials or stock movements recorded yet.")

    transactions = pd.DataFrame(execute_query(
        db_config, "SELECT txn_date FROM transactions;", fetch=True))
    projects = pd.DataFrame(execute_query(
        db_config, "SELECT start_date, end_date FROM projects;", fetch=True))

    movements["movement_date"] = pd.to_datetime(movements["movement_date"])
    movements["quantity"] = movements["quantity"].astype(float)
    movements["period_month"] = movements["movement_date"].values.astype("datetime64[M]")

    pivot = (movements.pivot_table(
        index=["material_id", "period_month"], columns="movement_type",
        values="quantity", aggfunc="sum", fill_value=0,
    ).reset_index())
    for col in ("ISSUANCE", "RECEIPT"):
        if col not in pivot.columns:
            pivot[col] = 0.0

    all_months = pd.date_range(
        movements["period_month"].min(),
        movements["period_month"].max(), freq="MS")
    grid = pd.MultiIndex.from_product(
        [materials["material_id"], all_months],
        names=["material_id", "period_month"]).to_frame(index=False)

    df = grid.merge(pivot, on=["material_id", "period_month"], how="left").fillna(0.0)
    df = df.rename(columns={"ISSUANCE": "demand_qty", "RECEIPT": "receipts"})
    df = df.sort_values(["material_id", "period_month"])

    df["net"] = df["receipts"] - df["demand_qty"]
    df["inventory_balance"] = df.groupby("material_id")["net"].cumsum().clip(lower=0)

    df = df.merge(materials[["material_id", "unit_cost"]], on="material_id", how="left")
    df["unit_cost"] = df["unit_cost"].astype(float)
    df["inventory_value"] = df["inventory_balance"] * df["unit_cost"]

    if not transactions.empty:
        transactions["txn_date"] = pd.to_datetime(transactions["txn_date"])
        txn = (transactions.assign(
            period_month=transactions["txn_date"].values.astype("datetime64[M]")
        ).groupby("period_month").size().rename("transaction_volume").reset_index())
        df = df.merge(txn, on="period_month", how="left")
    df["transaction_volume"] = df.get("transaction_volume", 0)
    df["transaction_volume"] = df["transaction_volume"].fillna(0).astype(int)

    df["active_projects"] = 0
    if not projects.empty:
        projects["start_date"] = pd.to_datetime(projects["start_date"])
        projects["end_date"] = pd.to_datetime(projects["end_date"])
        for m in all_months:
            m_start = m
            m_end = m + pd.offsets.MonthEnd(0)
            mask = (projects["start_date"] <= m_end) & (
                projects["end_date"].isna() | (projects["end_date"] >= m_start))
            df.loc[df["period_month"] == m, "active_projects"] = int(mask.sum())

    execute_query(db_config, "TRUNCATE TABLE monthly_demand RESTART IDENTITY;")
    rows = [(int(r["material_id"]), r["period_month"].date(), float(r["demand_qty"]),
             int(r["transaction_volume"]), float(r["inventory_balance"]),
             float(r["inventory_value"]), int(r["active_projects"]))
            for _, r in df.iterrows()]
    bulk_insert(db_config,
        """INSERT INTO monthly_demand
             (material_id, period_month, demand_qty, transaction_volume,
              inventory_balance, inventory_value, active_projects)
           VALUES %s;""", rows)
    return len(df)


# Feature engineering
def _movement_weather_by_month(db_config):
    try:
        rows = execute_query(
            db_config,
            """WITH d AS (
                   SELECT movement_date,
                          MAX(weather_temp_c)      AS t,
                          MAX(weather_rainfall_mm) AS r
                     FROM stock_movements
                    WHERE weather_temp_c IS NOT NULL OR weather_rainfall_mm IS NOT NULL
                    GROUP BY movement_date)
               SELECT date_trunc('month', movement_date)::date AS period_month,
                      COUNT(*)                                  AS n_days,
                      AVG(t)                                    AS avg_temp,
                      AVG(r)                                    AS avg_rain,
                      AVG(CASE WHEN r IS NULL THEN NULL WHEN r >= 1 THEN 1.0 ELSE 0.0 END) AS wet_share
                 FROM d GROUP BY 1 ORDER BY 1;""",
            fetch=True)
    except Exception:
        return {}
    out = {}
    for r in rows or []:
        if int(r["n_days"]) < MIN_MOVEMENT_WEATHER_DAYS:
            continue
        pm = pd.Timestamp(r["period_month"])
        dim = pm.days_in_month
        temp = None if r["avg_temp"] is None else float(r["avg_temp"])
        rain = None if r["avg_rain"] is None else float(r["avg_rain"]) * dim
        wet = None if r["wet_share"] is None else float(r["wet_share"]) * dim
        out[pm] = (temp, rain, wet)
    return out


def _load_panel(db_config):
    rows = execute_query(
        db_config,
        """SELECT md.material_id, md.period_month, md.demand_qty,
                  md.inventory_balance,
                  m.material_name, m.unit,
                  mw.avg_temp_c, mw.total_rainfall_mm, mw.rainy_days
             FROM monthly_demand md
             JOIN materials m ON m.material_id = md.material_id
        LEFT JOIN monthly_weather mw ON mw.period_month = md.period_month
            ORDER BY md.material_id, md.period_month;""",
        fetch=True,
    )
    if not rows:
        raise ValueError("monthly_demand is empty. Run aggregate_monthly_demand first.")
    df = pd.DataFrame(rows)
    df["period_month"] = pd.to_datetime(df["period_month"])
    df["demand_qty"] = df["demand_qty"].astype(float)
    df["inventory_balance"] = df["inventory_balance"].astype(float)
    for col in WEATHER_FEATURES:
        df[col] = df[col].astype(float)

    mv_weather = _movement_weather_by_month(db_config)
    months_from_movements = 0
    for pm, (t, r, w) in mv_weather.items():
        mask = df["period_month"] == pm
        if not mask.any():
            continue
        months_from_movements += 1
        for col, val in (("avg_temp_c", t), ("total_rainfall_mm", r), ("rainy_days", w)):
            if val is not None:
                df.loc[mask, col] = val
    df.attrs["movement_weather_months"] = months_from_movements
    df.attrs["weather_months"] = int(df.loc[df["total_rainfall_mm"].notna(), "period_month"].nunique())
    df.attrs["total_months"] = int(df["period_month"].nunique())

    for col in WEATHER_FEATURES:
        if df[col].notna().any():
            df[col] = df[col].fillna(df[col].mean())
        else:
            df[col] = df[col].fillna(0.0)
    return df


def prepare_dataset(panel):
    df = panel.copy().sort_values(["material_id", "period_month"])
    df["month"] = df["period_month"].dt.month
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
    g = df.groupby("material_id")["demand_qty"]
    df["prev_demand"] = g.shift(1)
    df["prev_demand_2"] = g.shift(2)
    df["prev_year_demand"] = g.shift(12)
    return df.dropna(subset=LAG_FEATURES).reset_index(drop=True)


def _metrics(y, p):
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    if len(y) == 0:
        return None
    nonzero = y != 0
    mape = float(np.mean(np.abs((y[nonzero] - p[nonzero]) / y[nonzero])) * 100) if nonzero.any() else None
    return {
        "mae": round(float(mean_absolute_error(y, p)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(y, p))), 3),
        "mape": round(mape, 2) if mape is not None else None,
        "r2": round(float(r2_score(y, p)), 4) if len(y) > 1 else None,
    }


class _Pooled:
    def __init__(self, train, feats):
        self.feats = feats
        self.materials = sorted(train["material_id"].unique())
        self.model = LinearRegression().fit(self._x(train), train["demand_qty"].astype(float))

    def _x(self, df):
        x = df[self.feats].astype(float).copy()
        for m in self.materials[1:]:
            x[f"mat_{m}"] = (df["material_id"] == m).astype(float)
        return x

    def predict(self, df):
        return self.model.predict(self._x(df))


def _fit_one(train, feats):
    return LinearRegression().fit(train[feats].astype(float), train["demand_qty"].astype(float))


def _predict_split(train, test, feats):
    preds = pd.Series(index=test.index, dtype=float)
    pooled = None
    for mid, part in test.groupby("material_id"):
        own = train[train["material_id"] == mid]
        if len(own) >= MIN_PER_MATERIAL_ROWS - 2:
            preds.loc[part.index] = _fit_one(own, feats).predict(part[feats].astype(float))
        else:
            if pooled is None:
                pooled = _Pooled(train, feats)
            if mid in pooled.materials:
                preds.loc[part.index] = pooled.predict(part)
            else:
                preds.loc[part.index] = part["prev_demand"].astype(float)
    return preds.clip(lower=0)


def evaluate(df):
    months = sorted(df["period_month"].unique())
    holdout = min(MAX_HOLDOUT_MONTHS, len(months) // 4)
    if holdout < MIN_HOLDOUT_MONTHS:
        return None
    test_months = months[-holdout:]
    train = df[df["period_month"] < test_months[0]]
    test = df[df["period_month"] >= test_months[0]]
    if len(train) < MIN_TRAINING_ROWS or test.empty:
        return None
    y = test["demand_qty"].astype(float)
    full = _metrics(y, _predict_split(train, test, FEATURES))
    no_weather = _metrics(y, _predict_split(train, test, FEATURES_NO_WEATHER))
    naive = _metrics(y, test["prev_demand"].astype(float))
    improvement = None
    if no_weather and no_weather["mae"]:
        improvement = round((no_weather["mae"] - full["mae"]) / no_weather["mae"] * 100, 1)
    return {
        "holdout_months": holdout,
        "test_period": f"{pd.Timestamp(test_months[0]).strftime('%b %Y')} - {pd.Timestamp(test_months[-1]).strftime('%b %Y')}",
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "models": [
            {"name": MODEL_NAME, **full},
            {"name": NO_WEATHER_NAME, **no_weather},
            {"name": NAIVE_NAME, **naive},
        ],
        "weather_improvement_pct": improvement,
        "weather_helps": improvement is not None and improvement >= WEATHER_HELPS_THRESHOLD,
        "beats_naive": bool(naive and full["mae"] < naive["mae"]),
    }


def _forecast_weather(df, forecast_month, overrides):
    same = df[df["month"] == forecast_month.month]
    source = same if len(same) else df
    wx = {col: float(source[col].mean()) for col in WEATHER_FEATURES}
    estimated = True
    for k in WEATHER_FEATURES:
        if overrides and k in overrides:
            wx[k] = float(overrides[k])
            estimated = False
    return wx, estimated


def _weather_insight(model, feats, unit):
    coefs = dict(zip(feats, model.coef_))
    rain10 = float(coefs.get("total_rainfall_mm", 0.0)) * 10
    day = float(coefs.get("rainy_days", 0.0))
    if abs(day) < 0.05 and abs(rain10) < 0.05:
        return "No clear link between weather and this material's demand in the data so far.", 0.0
    direction = "more" if day >= 0 else "less"
    return (f"In past data, each extra rainy day in a month went with about {abs(day):.2f} {unit} "
            f"{direction} demand (other factors held the same)."), round(day, 4)


def _risk(predicted, stock):
    if predicted <= 0:
        return "OK", None
    days = round(stock / (predicted / 30.0), 1)
    if stock < predicted:
        return "Will run out", days
    if stock < predicted * 1.25:
        return "Low", days
    return "OK", days


def run_forecast(db_config, overrides=None, username="system"):
    panel = _load_panel(db_config)
    movement_weather_months = int(panel.attrs.get("movement_weather_months", 0))
    total_months = int(panel.attrs.get("total_months", 0))
    df = prepare_dataset(panel)
    if len(df) < MIN_TRAINING_ROWS:
        raise ValueError(
            f"Only {len(df)} usable monthly rows (need at least {MIN_TRAINING_ROWS}). "
            "Record more Stock Out history first.")

    evaluation = evaluate(df)

    forecast_month = (df["period_month"].max() + pd.offsets.MonthBegin(1)).normalize()
    wx, estimated = _forecast_weather(df, forecast_month, overrides)
    season = {"month_sin": float(np.sin(2 * np.pi * forecast_month.month / 12)),
              "month_cos": float(np.cos(2 * np.pi * forecast_month.month / 12))}

    full_panel = panel.sort_values(["material_id", "period_month"])
    stock_rows = execute_query(db_config, "SELECT material_id, current_stock FROM materials;", fetch=True)
    stock_by_id = {int(r["material_id"]): float(r["current_stock"]) for r in stock_rows}
    pooled = None
    forecasts, insert_rows = [], []

    materials = df[["material_id", "material_name", "unit"]].drop_duplicates().sort_values("material_name")
    for _, mat in materials.iterrows():
        mid = int(mat["material_id"])
        own = df[df["material_id"] == mid]
        hist = full_panel[full_panel["material_id"] == mid]
        prev1 = float(hist["demand_qty"].iloc[-1])
        prev2 = float(hist["demand_qty"].iloc[-2]) if len(hist) > 1 else prev1
        # Same-month-last-year demand for the month being forecasted.
        # hist ends at the latest recorded month; forecast_month is one month
        # after that, so prev_year_demand sits 12 positions back from the end.
        prev12 = float(hist["demand_qty"].iloc[-12]) if len(hist) >= 12 else prev1
        row = pd.DataFrame([{"material_id": mid, "prev_demand": prev1, "prev_demand_2": prev2,
                             "prev_year_demand": prev12,
                             **season, "total_rainfall_mm": wx["total_rainfall_mm"],
                             "rainy_days": wx["rainy_days"]}])
        if len(own) >= MIN_PER_MATERIAL_ROWS - 2:
            model = _fit_one(own, FEATURES)
            predicted_raw = float(model.predict(row[FEATURES].astype(float))[0])
            insight, rain_coef = _weather_insight(model, FEATURES, mat["unit"])
            model_type = "per-material"
        else:
            if pooled is None:
                pooled = _Pooled(df, FEATURES)
            predicted_raw = float(pooled.predict(row)[0])
            insight, rain_coef = _weather_insight(pooled.model, FEATURES, mat["unit"])
            insight = "Not enough history for its own model yet, so this uses the combined model. " + insight
            model_type = "pooled"

        predicted = max(round(predicted_raw, 2), 0.0)
        stock = stock_by_id.get(mid, 0.0)
        risk, days_cover = _risk(predicted, stock)
        recent = hist.tail(6)
        forecasts.append({
            "material_id": mid,
            "material_name": mat["material_name"],
            "unit": mat["unit"],
            "predicted_demand": predicted,
            "current_stock": round(stock, 2),
            "reorder_qty": max(round(predicted - stock, 2), 0.0),
            "prev_demand": round(prev1, 2),
            "risk": risk,
            "days_of_cover": days_cover,
            "history": [{"month": pm.strftime("%b %Y"), "demand": round(float(d), 2),
                         "inventory": round(float(b), 2)}
                        for pm, d, b in zip(recent["period_month"], recent["demand_qty"],
                                            recent["inventory_balance"])],
            "forecast_label": forecast_month.strftime("%b %Y"),
            "model_type": model_type,
            "training_rows": int(len(own)),
            "sample_size_warning": len(own) < SAMPLE_SIZE_WARN_THRESHOLD,
            "rainy_day_effect": rain_coef,
            "weather_insight": insight,
        })
        insert_rows.append((mid, forecast_month.date(), predicted, MODEL_NAME))

    if not forecasts:
        raise ValueError("No materials have history to forecast against.")

    bulk_insert(db_config,
        """INSERT INTO forecast_results (material_id, forecast_month, predicted_demand, model_name)
           VALUES %s
           ON CONFLICT (material_id, forecast_month, model_name) DO UPDATE SET
             predicted_demand = EXCLUDED.predicted_demand, generated_at = CURRENT_TIMESTAMP;""",
        insert_rows)

    if evaluation:
        for m in reversed(evaluation["models"]):
            execute_query(db_config, """
                INSERT INTO model_metrics (model_name, mae, rmse, mape, r2, train_rows, test_rows, features_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (m["name"], m["mae"], m["rmse"], m["mape"], m["r2"], evaluation["train_rows"],
                  evaluation["test_rows"],
                  ", ".join(FEATURES if m["name"] == MODEL_NAME else
                            FEATURES_NO_WEATHER if m["name"] == NO_WEATHER_NAME else ["prev_demand"])))

    result = {
        "model": MODEL_NAME,
        "forecast_month": forecast_month.strftime("%B %Y"),
        "forecast_date": str(forecast_month.date()),
        "features_used": FEATURES,
        "evaluation": evaluation,
        "summary": {
            "materials": len(forecasts),
            "will_run_out": sum(1 for f in forecasts if f["risk"] == "Will run out"),
            "low": sum(1 for f in forecasts if f["risk"] == "Low"),
            "per_material": sum(1 for f in forecasts if f["model_type"] == "per-material"),
            "pooled": sum(1 for f in forecasts if f["model_type"] == "pooled"),
        },
        "forecasts": forecasts,
        "weather": {
            "available": int(panel.attrs.get("weather_months", 0)) > 0,
            "location": LOCATION_NAME,
            "avg_temp_c": round(wx["avg_temp_c"], 1),
            "total_rainfall_mm": round(wx["total_rainfall_mm"], 1),
            "rainy_days": round(wx["rainy_days"], 1),
            "source": "manual override" if not estimated else
                      f"average of past {forecast_month.strftime('%B')} months",
        },
        "training_weather": {
            "months_from_stock_movements": movement_weather_months,
            "months_total": total_months,
        },
    }

    ev = evaluation["models"][0] if evaluation else None
    log_audit(db_config, "RUN_FORECAST",
              f"{MODEL_NAME} for {forecast_month.date()}: {len(forecasts)} materials. "
              + (f"Hold-out MAE={ev['mae']}, MAPE={ev['mape']}%." if ev else "Not enough history to test."),
              username)
    execute_query(db_config, "INSERT INTO forecast_runs (run_by, result) VALUES (%s, %s::jsonb);",
                  (username, json.dumps(result, default=str)))
    return result


def get_latest_run(db_config):
    try:
        rows = execute_query(db_config, """
            SELECT run_at, run_by, result FROM forecast_runs ORDER BY run_id DESC LIMIT 1;
        """, fetch=True)
    except Exception:
        return None
    if not rows:
        return None
    result = rows[0]["result"]
    if isinstance(result, str):
        result = json.loads(result)
    result["run_at"] = rows[0]["run_at"].isoformat() if rows[0]["run_at"] else None
    result["run_by"] = rows[0]["run_by"]
    return result
