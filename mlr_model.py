"""
Parabellum ISOS - Demand Forecasting Service
=================================================================
Multiple Linear Regression for MONTHLY MATERIAL DEMAND.

TRANSFER NOTE
-------------
This file replaces the previous ISOS mlr_model.py. It ports the
**MLR methodology from the demo video / parabellum-app version** into
the ISOS project:

    Feature set     calendar features + weather + one-hot MATERIAL
                    (year, month, day_of_week + weather favorability
                    index + one column per material)

    Evaluation      in-sample MAE / RMSE / R^2 (train == test), as in
                    the video.

    Model           a single pooled sklearn.LinearRegression across
                    ALL materials, PLUS per-material MLRs (one per
                    material with enough history) as the primary output.

Kept from the previous ISOS module (so app.py needs no changes):
    * function names execute_query, log_audit, get_materials,
      aggregate_monthly_demand, run_forecast
    * schema targets: monthly_demand (D4), forecast_results (D5),
      model_metrics (D6), audit_logs (D7), monthly_weather (D8)
    * audit logging, structured errors, `overrides` for what-if
      planning, MIN_TRAINING_ROWS guard.
"""

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

MODEL_NAME = "Multiple Linear Regression"

# Calendar features -- transferred from the video's MLR.
CALENDAR_FEATURES = ["year", "month", "day_of_week"]

# Weather features -- from monthly_weather (D8), synced via weather_api.py
# from Open-Meteo for Lipa City, Batangas.
WEATHER_FEATURES = ["avg_temp_c", "total_rainfall_mm", "rainy_days"]

# ---------------------------------------------------------------------
# Weather Favorability Index -- one 0-100 score, deterministic feature
# engineering from the three raw weather columns. This defines what
# counts as "pleasant vs. harsh" weather; the regression learns whether
# that relates to more or less demand (data-driven, not assumed).
MODEL_WEATHER_FEATURE = "weather_favorability_index"

IDEAL_TEMP_C = 27.0
TEMP_TOLERANCE_C = 5.0
MAX_MONTHLY_RAINFALL_MM = 300.0
MAX_MONTHLY_RAINY_DAYS = 20

TEMP_PENALTY_WEIGHT = 20
RAIN_PENALTY_WEIGHT = 50
RAINY_DAYS_PENALTY_WEIGHT = 30

# LOCATION_NAME duplicated (not imported) from weather_api.py to avoid
# a circular import: weather_api imports helpers from mlr_model.
LOCATION_NAME = "Lipa City, Batangas, PH"

# Cyclic (sine/cosine) encoding of the calendar month for the per-material
# models. Wraps Dec (12) close to Jan (1).
MONTH_CYCLIC_FEATURES = ["month_sin", "month_cos"]

# Lagged demand features -- serial-correlation signal per material.
LAG_FEATURES = ["prev_demand", "prev_demand_2"]

# Per-material MLR feature set: weather primary + cyclic month + lags.
PER_MATERIAL_FEATURES = LAG_FEATURES + [MODEL_WEATHER_FEATURE] + MONTH_CYCLIC_FEATURES

# Minimum row counts.
MIN_TRAINING_ROWS = 20        # pooled model
MIN_PER_MATERIAL_ROWS = 15    # per-material model (needs 13 usable rows after lag dropna)
SAMPLE_SIZE_WARN_THRESHOLD = 24


# =================================================================
# Database helpers
# =================================================================
def connect_db(db_config):
    return psycopg2.connect(**db_config)


def execute_query(db_config, query, params=None, fetch=False):
    conn = connect_db(db_config)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            result = cur.fetchall() if fetch else None
        conn.commit()
        return result
    finally:
        conn.close()


def log_audit(db_config, action, details, username="system"):
    """D7 audit log; never breaks a forecast if it fails."""
    try:
        execute_query(
            db_config,
            "INSERT INTO audit_logs (username, action, details) VALUES (%s, %s, %s);",
            (username, action, details),
        )
    except Exception:
        pass


def _bulk_insert(db_config, sql, rows, page_size=500):
    """
    Batch INSERT via psycopg2.extras.execute_values.
    Collapses N round-trips into 1 or N/page_size. `sql` must contain
    a single %s placeholder where the VALUES tuples go.
    """
    if not rows:
        return
    conn = connect_db(db_config)
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=page_size)
        conn.commit()
    finally:
        conn.close()


# =================================================================
# Master data
# =================================================================
def get_materials(db_config):
    """Material master (D2) -- populates UI dropdown."""
    rows = execute_query(
        db_config,
        """SELECT material_id, material_code, material_name, unit,
                  unit_cost, current_stock, reorder_level
             FROM materials ORDER BY material_name;""",
        fetch=True,
    )
    return [dict(r) for r in rows]


def get_forecast_history(db_config, limit=15):
    """
    Prediction History table on the forecasting page: past forecast
    rows from D5 LEFT JOINed against the actual demand (D4) that came
    in later, most recent first.

    Accuracy = max(0, 100 - |predicted - actual| / actual * 100); None
    when actual isn't in yet.
    """
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
        actual = float(r["actual_demand"]) if r["actual_demand"] is not None else None
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


# =================================================================
# Weather Favorability Index + insight
# =================================================================
def compute_weather_favorability(avg_temp_c, total_rainfall_mm, rainy_days):
    """0-100 score. 100 = ideal, 0 = worst case on all axes."""
    temp_dev = np.abs(np.asarray(avg_temp_c, dtype=float) - IDEAL_TEMP_C)
    temp_penalty = np.minimum(temp_dev / TEMP_TOLERANCE_C, 1.0) * TEMP_PENALTY_WEIGHT

    rain_penalty = np.minimum(
        np.asarray(total_rainfall_mm, dtype=float) / MAX_MONTHLY_RAINFALL_MM, 1.0
    ) * RAIN_PENALTY_WEIGHT

    days_penalty = np.minimum(
        np.asarray(rainy_days, dtype=float) / MAX_MONTHLY_RAINY_DAYS, 1.0
    ) * RAINY_DAYS_PENALTY_WEIGHT

    return np.clip(100.0 - temp_penalty - rain_penalty - days_penalty, 0.0, 100.0)


def weather_favorability_label(index):
    if index >= 70: return "Favorable"
    if index >= 40: return "Moderate"
    return "Unfavorable"


def _weather_effect_insight(weather_coef, unit="units"):
    """Turn fitted weather coefficient into plain-language sentence."""
    NOISE_FLOOR = 0.05
    if weather_coef > NOISE_FLOOR:
        return (f"In your historical data, better weather is associated with HIGHER "
                f"demand: each +1 point of favorability corresponds to about "
                f"{weather_coef:.2f} more {unit} predicted, holding month and material fixed.")
    if weather_coef < -NOISE_FLOOR:
        return (f"In your historical data, better weather is associated with LOWER "
                f"demand: each +1 point of favorability corresponds to about "
                f"{abs(weather_coef):.2f} fewer {unit} predicted, holding month and material fixed. "
                f"(i.e. worse weather -- more rain, more rainy days -- is associated with higher demand here.)")
    return (f"No meaningful weather relationship was detected in your historical data "
            f"(coefficient {weather_coef:+.3f} is within noise). Demand doesn't appear "
            f"to track weather favorability for these materials.")


# =================================================================
# DFD 3.2 -- Aggregate Monthly Demand
# =================================================================
def aggregate_monthly_demand(db_config):
    """
    Rebuild monthly_demand (D4) from raw operational records.
    Batched insert via _bulk_insert (was: N*M round-trips).
    """
    materials = pd.DataFrame(execute_query(
        db_config,
        "SELECT material_id, material_name, unit_cost FROM materials;",
        fetch=True,
    ))
    movements = pd.DataFrame(execute_query(
        db_config,
        "SELECT material_id, movement_type, quantity, movement_date FROM stock_movements;",
        fetch=True,
    ))
    if materials.empty or movements.empty:
        raise ValueError("No materials or stock movements found. Run schema.sql, then seed_data.py.")

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
    _bulk_insert(db_config,
        """INSERT INTO monthly_demand
             (material_id, period_month, demand_qty, transaction_volume,
              inventory_balance, inventory_value, active_projects)
           VALUES %s;""", rows)
    return len(df)


# =================================================================
# Feature engineering
# =================================================================
def _load_panel(db_config):
    """Panel: monthly_demand LEFT JOIN monthly_weather, with materials info."""
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
        if df[col].notna().any():
            df[col] = df[col].fillna(df[col].mean())
        else:
            df[col] = df[col].fillna(0.0)
    return df


def prepare_mlr_dataset(panel):
    """Build design matrix: calendar + weather index + cyclic month + lags + one-hot material."""
    df = panel.copy()
    df["year"] = df["period_month"].dt.year
    df["month"] = df["period_month"].dt.month
    df["day_of_week"] = df["period_month"].dt.dayofweek

    df[MODEL_WEATHER_FEATURE] = compute_weather_favorability(
        df["avg_temp_c"], df["total_rainfall_mm"], df["rainy_days"])

    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)

    df = df.sort_values(["material_id", "period_month"])
    g = df.groupby("material_id")["demand_qty"]
    df["prev_demand"]   = g.shift(1)
    df["prev_demand_2"] = g.shift(2)

    encoded = pd.get_dummies(df["material_name"], prefix="mat")

    final_df = pd.concat([
        df[["material_id", "material_name", "unit", "period_month",
            "year", "month", "day_of_week",
            "demand_qty", "inventory_balance"]
           + WEATHER_FEATURES + [MODEL_WEATHER_FEATURE]
           + MONTH_CYCLIC_FEATURES + LAG_FEATURES],
        encoded,
    ], axis=1)
    return final_df


def _mape(y_true, y_pred):
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    mask = y_true != 0
    if not mask.any(): return None
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _fit_material_model(mat_df, unit="units", feature_set=None):
    """Fit weather-primary MLR for one material. feature_set defaults to PER_MATERIAL_FEATURES."""
    if feature_set is None:
        feature_set = PER_MATERIAL_FEATURES
    X = mat_df[feature_set].astype(float)
    y = mat_df["demand_qty"].astype(float)

    model = LinearRegression()
    model.fit(X, y)
    y_pred = model.predict(X)

    coefs = dict(zip(feature_set, model.coef_))
    weather_coef = float(coefs.get(MODEL_WEATHER_FEATURE, 0.0))
    mape_val = _mape(y.values, y_pred)

    return {
        "model":               model,
        "features":            feature_set,
        "coefficients":        {k: round(float(v), 4) for k, v in coefs.items()},
        "intercept":           round(float(model.intercept_), 4),
        "weather_coefficient": round(weather_coef, 4),
        "weather_insight":     _weather_effect_insight(weather_coef, unit=unit),
        "metrics": {
            "mae":  round(float(mean_absolute_error(y, y_pred)), 3),
            "rmse": round(float(np.sqrt(mean_squared_error(y, y_pred))), 3),
            "mape": round(mape_val, 2) if mape_val is not None else None,
            "r2":   round(float(r2_score(y, y_pred)), 4) if len(mat_df) > 1 else 0.0,
        },
        "training_rows": int(len(mat_df)),
    }


# =================================================================
# DFD 4 -- Train, evaluate, forecast, save
# =================================================================
def run_forecast(db_config, overrides=None, test_ratio=None, username="system"):
    """
    Two-stage forecast with weather as primary demand driver:
      STAGE 1: pooled MLR (video-style, all materials one-hot). Used
               as baseline metrics AND as fallback for materials with
               < MIN_PER_MATERIAL_ROWS history.
      STAGE 2: per-material MLR (weather + cyclic month + lags), the
               primary output for materials with enough history.
    Auto-fallback: if lag-dropna leaves too few rows to train, both
    tiers automatically fall back to a lag-free feature set.
    """
    panel = _load_panel(db_config)
    df = prepare_mlr_dataset(panel)

    if len(df) < MIN_TRAINING_ROWS:
        raise ValueError(
            f"Only {len(df)} monthly rows available (need at least {MIN_TRAINING_ROWS}). "
            f"Add more history, then re-run the aggregation.")

    encoded_cols = [c for c in df.columns if c.startswith("mat_")]

    # Prefer training WITH lag features; auto-fall-back if too thin.
    df_lagged = df.dropna(subset=LAG_FEATURES)
    if len(df_lagged) >= MIN_TRAINING_ROWS:
        pooled_train_df = df_lagged
        feature_cols = LAG_FEATURES + CALENDAR_FEATURES + [MODEL_WEATHER_FEATURE] + encoded_cols
        pooled_uses_lags = True
    else:
        pooled_train_df = df
        feature_cols = CALENDAR_FEATURES + [MODEL_WEATHER_FEATURE] + encoded_cols
        pooled_uses_lags = False

    # ---- Pooled fit ----
    X = pooled_train_df[feature_cols].astype(float)
    y = pooled_train_df["demand_qty"].astype(float)
    model = LinearRegression()
    model.fit(X, y)

    y_pred_train = model.predict(X)
    mape_val = _mape(y, y_pred_train)
    metrics = {
        "mae":   round(float(mean_absolute_error(y, y_pred_train)), 3),
        "rmse":  round(float(np.sqrt(mean_squared_error(y, y_pred_train))), 3),
        "mape":  round(mape_val, 2) if mape_val is not None else None,
        "r2":    round(float(r2_score(y, y_pred_train)), 4) if len(pooled_train_df) > 1 else 0.0,
        "train_rows":  int(len(pooled_train_df)),
        "test_rows":   int(len(pooled_train_df)),
        "evaluation":  "in-sample (train == test)",
        "uses_lag_features": pooled_uses_lags,
    }

    execute_query(db_config,
        """INSERT INTO model_metrics
             (model_name, mae, rmse, mape, r2, train_rows, test_rows, features_used)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
        (MODEL_NAME, metrics["mae"], metrics["rmse"], metrics["mape"],
         metrics["r2"], metrics["train_rows"], metrics["test_rows"],
         ", ".join(feature_cols)))

    coefficients = {f: round(float(c), 4)
                    for f, c in zip(feature_cols, model.coef_)
                    if f in CALENDAR_FEATURES or f == MODEL_WEATHER_FEATURE or f in LAG_FEATURES}

    # ---- Forecast month setup ----
    latest_month = df["period_month"].max()
    forecast_month = (latest_month + pd.offsets.MonthBegin(1)).normalize()

    fm_features = {
        "year": forecast_month.year,
        "month": forecast_month.month,
        "day_of_week": forecast_month.dayofweek,
    }
    # Seasonal-climatology estimate for weather in the forecast month
    same_month_history = df[df["month"] == forecast_month.month]
    for col in WEATHER_FEATURES:
        if len(same_month_history) > 0:
            fm_features[col] = float(same_month_history[col].mean())
        else:
            fm_features[col] = float(df[col].mean())
    weather_is_estimated = True

    if overrides:
        for k, v in overrides.items():
            if k in CALENDAR_FEATURES or k in WEATHER_FEATURES:
                fm_features[k] = float(v)
                if k in WEATHER_FEATURES:
                    weather_is_estimated = False

    fm_features[MODEL_WEATHER_FEATURE] = float(compute_weather_favorability(
        fm_features["avg_temp_c"], fm_features["total_rainfall_mm"], fm_features["rainy_days"]))

    fm_features["month_sin"] = float(np.sin(2 * np.pi * forecast_month.month / 12))
    fm_features["month_cos"] = float(np.cos(2 * np.pi * forecast_month.month / 12))

    materials_seen = (df[["material_id", "material_name", "unit"]]
                      .drop_duplicates().sort_values("material_name"))

    # Preload current_stock in one query
    stock_rows = execute_query(db_config,
        "SELECT material_id, current_stock FROM materials;", fetch=True)
    stock_by_id = {int(r["material_id"]): float(r["current_stock"]) for r in stock_rows}

    pooled_weather_coef = round(float(coefficients[MODEL_WEATHER_FEATURE]), 4)
    pooled_weather_insight = _weather_effect_insight(
        pooled_weather_coef,
        unit=materials_seen["unit"].mode().iat[0] if len(materials_seen) else "units")

    forecasts = []
    forecast_insert_rows = []
    per_material_metrics = []
    n_per_material_fits = 0
    n_pooled_fallbacks = 0
    HISTORY_MONTHS = 6

    for _, mrow in materials_seen.iterrows():
        mat_df = df[df["material_id"] == int(mrow["material_id"])].sort_values("period_month")

        prev1 = float(mat_df["demand_qty"].iloc[-1]) if len(mat_df) >= 1 else 0.0
        prev2 = float(mat_df["demand_qty"].iloc[-2]) if len(mat_df) >= 2 else prev1

        mat_df_lagged = mat_df.dropna(subset=LAG_FEATURES)
        can_fit_per_material = len(mat_df) >= MIN_PER_MATERIAL_ROWS

        if can_fit_per_material:
            if len(mat_df_lagged) >= MIN_PER_MATERIAL_ROWS - 2:
                fit = _fit_material_model(mat_df_lagged, unit=mrow["unit"],
                                          feature_set=PER_MATERIAL_FEATURES)
                per_mat_features = PER_MATERIAL_FEATURES
            else:
                lagless = [f for f in PER_MATERIAL_FEATURES if f not in LAG_FEATURES]
                fit = _fit_material_model(mat_df, unit=mrow["unit"], feature_set=lagless)
                per_mat_features = lagless
            model_type = "per-material"
            n_per_material_fits += 1

            row_dict = {
                "prev_demand":         prev1,
                "prev_demand_2":       prev2,
                MODEL_WEATHER_FEATURE: fm_features[MODEL_WEATHER_FEATURE],
                "month_sin":           fm_features["month_sin"],
                "month_cos":           fm_features["month_cos"],
            }
            X_next = pd.DataFrame([row_dict])[per_mat_features].astype(float)
            predicted_raw = float(fit["model"].predict(X_next)[0])

            weather_coefficient = fit["weather_coefficient"]
            weather_insight = fit["weather_insight"]
            material_metrics = fit["metrics"]
        else:
            model_type = "pooled fallback"
            n_pooled_fallbacks += 1

            one_hot_col = f"mat_{mrow['material_name']}"
            if one_hot_col not in encoded_cols:
                continue

            row = dict(fm_features)
            if pooled_uses_lags:
                row["prev_demand"] = prev1
                row["prev_demand_2"] = prev2
            for col in encoded_cols:
                row[col] = 0
            row[one_hot_col] = 1
            X_next = pd.DataFrame([row])[feature_cols].astype(float)
            predicted_raw = float(model.predict(X_next)[0])

            weather_coefficient = pooled_weather_coef
            weather_insight = (
                f"Not enough history for a material-specific fit ({len(mat_df)} months); "
                f"falling back to the pooled average. " + pooled_weather_insight)
            material_metrics = {
                "mae": metrics["mae"], "rmse": metrics["rmse"],
                "mape": metrics["mape"], "r2": metrics["r2"],
            }

        predicted = max(round(predicted_raw, 2), 0.0)
        stock = stock_by_id.get(int(mrow["material_id"]), 0.0)
        reorder = max(round(predicted - stock, 2), 0.0)
        sample_warning = len(mat_df) < SAMPLE_SIZE_WARN_THRESHOLD

        mat_hist = mat_df.tail(HISTORY_MONTHS)
        history = [{"month": pm.strftime("%b %Y"),
                    "demand": round(float(d), 2),
                    "inventory": round(float(b), 2)}
                   for pm, d, b in zip(mat_hist["period_month"],
                                       mat_hist["demand_qty"],
                                       mat_hist["inventory_balance"])]
        prev_demand = prev1

        forecast_insert_rows.append(
            (int(mrow["material_id"]), forecast_month.date(), predicted, MODEL_NAME))

        forecasts.append({
            "material_id":         int(mrow["material_id"]),
            "material_name":       mrow["material_name"],
            "unit":                mrow["unit"],
            "predicted_demand":    predicted,
            "current_stock":       round(stock, 2),
            "reorder_qty":         reorder,
            "prev_demand":         round(prev_demand, 2),
            "history":             history,
            "forecast_label":      forecast_month.strftime("%b %Y"),
            "model_type":          model_type,
            "training_rows":       int(len(mat_df)),
            "sample_size_warning": sample_warning,
            "weather_coefficient": weather_coefficient,
            "weather_insight":     weather_insight,
            "material_metrics":    material_metrics,
        })
        if model_type == "per-material":
            per_material_metrics.append(material_metrics)

    if not forecasts:
        raise ValueError("No materials have history to forecast against.")

    _bulk_insert(db_config,
        """INSERT INTO forecast_results
             (material_id, forecast_month, predicted_demand, model_name)
           VALUES %s
           ON CONFLICT (material_id, forecast_month, model_name) DO UPDATE SET
             predicted_demand = EXCLUDED.predicted_demand,
             generated_at     = CURRENT_TIMESTAMP;""",
        forecast_insert_rows)

    if per_material_metrics:
        mape_vals = [m["mape"] for m in per_material_metrics if m["mape"] is not None]
        per_material_summary = {
            "n_per_material":    n_per_material_fits,
            "n_pooled_fallback": n_pooled_fallbacks,
            "avg_mae":  round(float(np.mean([m["mae"]  for m in per_material_metrics])), 3),
            "avg_rmse": round(float(np.mean([m["rmse"] for m in per_material_metrics])), 3),
            "avg_mape": round(float(np.mean(mape_vals)), 2) if mape_vals else None,
            "avg_r2":   round(float(np.mean([m["r2"]   for m in per_material_metrics])), 4),
        }
    else:
        per_material_summary = {
            "n_per_material": 0, "n_pooled_fallback": n_pooled_fallbacks,
            "avg_mae": None, "avg_rmse": None, "avg_mape": None, "avg_r2": None,
        }

    log_audit(db_config, "RUN_FORECAST",
        f"{MODEL_NAME} for {forecast_month.date()}: {len(forecasts)} materials "
        f"({n_per_material_fits} per-material, {n_pooled_fallbacks} pooled-fallback). "
        f"Pooled R2={metrics['r2']}, MAE={metrics['mae']}, "
        f"uses_lag_features={pooled_uses_lags}. "
        f"Weather: {'overridden' if not weather_is_estimated else 'estimated (seasonal)'}.",
        username)

    return {
        "model":            MODEL_NAME,
        "model_strategy":   f"per-material MLR (lags + weather + cyclic month) with pooled "
                            f"fallback for < {MIN_PER_MATERIAL_ROWS} months",
        "forecast_month":   forecast_month.strftime("%B %Y"),
        "forecast_date":    str(forecast_month.date()),
        "metrics":          metrics,
        "coefficients":     coefficients,
        "intercept":        round(float(model.intercept_), 4),
        "features_used":    feature_cols,
        "per_material_summary": per_material_summary,
        "forecasts":        forecasts,
        "weather": {
            "location":            LOCATION_NAME,
            "avg_temp_c":          round(fm_features["avg_temp_c"], 2),
            "total_rainfall_mm":   round(fm_features["total_rainfall_mm"], 2),
            "rainy_days":          round(fm_features["rainy_days"], 1),
            "favorability_index":  round(fm_features[MODEL_WEATHER_FEATURE], 1),
            "favorability_label":  weather_favorability_label(fm_features[MODEL_WEATHER_FEATURE]),
            "source": "override" if not weather_is_estimated
                      else "seasonal estimate (avg of this calendar month in past years)",
        },
    }
