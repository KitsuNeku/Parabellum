"""
Parabellum ISOS — Demand Forecasting Service
=================================================================
Multiple Linear Regression for SHORT-TERM MONTHLY MATERIAL DEMAND.

This file implements what the capstone documentation actually specifies:

  Objective 3.2  short-term MONTHLY material demand   (not hourly orders)
  Predictors     past demand, transaction volume, inventory balance,
                 inventory value, project activity
  Objective 3.3  evaluated with MAE, RMSE, MAPE, and R2
  DFD 3.2        Aggregate Monthly Demand        -> D4 monthly_demand
  DFD 4.1        Preprocess Forecast Data
  DFD 4.2        Run Forecasting Model
  DFD 4.3        Evaluate Model                  -> D6 model_metrics
  DFD 4.4        Save Forecast Results           -> D5 forecast_results
  Appendix B     Audit Log Module                -> D7 audit_logs

Two things worth being able to defend out loud:

1. NO DATA LEAKAGE. Every predictor is something you already know BEFORE
   the forecast month starts. Demand is predicted from the PREVIOUS
   month's demand and transactions, and from the stock you are holding
   going INTO the month. (Using the same month's closing stock would leak
   the answer, because that month's demand is what depleted it.)

2. HONEST EVALUATION. The model is scored on months it never trained on,
   split chronologically — never shuffled, because this is time-series
   data and shuffling would let the model peek at the future.
"""

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor

from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

MODEL_NAME = "Multiple Linear Regression"

# The predictors named in the documentation.
FEATURES = [
    "prev_demand",       # past material demand      (month t-1)
    "prev_demand_2",     # past material demand      (month t-2) -> trend
    "prev_txn_volume",   # transaction volume        (month t-1)
    "opening_stock",     # inventory balance entering the month
    "opening_value",     # inventory value entering the month
    "active_projects",   # project activity scheduled for the month
]

# Below this, an MLR fit is not meaningful and we say so instead of
# returning a confident-looking number.
MIN_TRAINING_ROWS = 24


# =================================================================
#  Database helpers
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
    """D7 — Appendix B says forecast processing must be logged."""
    try:
        execute_query(
            db_config,
            "INSERT INTO audit_logs (username, action, details) VALUES (%s, %s, %s);",
            (username, action, details),
        )
    except Exception:
        # An audit-log failure must never break a forecast.
        pass


def get_materials(db_config):
    """Material master (D2) — used to populate the UI dropdown."""
    rows = execute_query(
        db_config,
        """SELECT material_id, material_code, material_name, unit,
                  unit_cost, current_stock, reorder_level
           FROM materials ORDER BY material_name;""",
        fetch=True,
    )
    return [dict(r) for r in rows]


# =================================================================
#  DFD 3.2 — Aggregate Monthly Demand  ->  D4
# =================================================================
def aggregate_monthly_demand(db_config):
    """
    Turn raw operational records into the forecasting-ready monthly panel.

        demand_qty         = material ISSUANCES in the month (what was consumed)
        inventory_balance  = running (receipts - issuances) to month end
        inventory_value    = inventory_balance x unit_cost
        transaction_volume = transactions recorded that month
        active_projects    = projects running during that month

    Writes one row per material per month into monthly_demand (D4).
    """
    materials = pd.DataFrame(execute_query(
        db_config,
        "SELECT material_id, material_name, unit_cost FROM materials;",
        fetch=True,
    ))
    movements = pd.DataFrame(execute_query(
        db_config,
        """SELECT material_id, movement_type, quantity, movement_date
           FROM stock_movements;""",
        fetch=True,
    ))

    if materials.empty or movements.empty:
        raise ValueError(
            "No materials or stock movements found. "
            "Run schema.sql, then seed_data.py."
        )

    transactions = pd.DataFrame(execute_query(
        db_config, "SELECT txn_date FROM transactions;", fetch=True
    ))
    projects = pd.DataFrame(execute_query(
        db_config, "SELECT start_date, end_date FROM projects;", fetch=True
    ))

    movements["movement_date"] = pd.to_datetime(movements["movement_date"])
    movements["quantity"] = movements["quantity"].astype(float)
    movements["period_month"] = movements["movement_date"].values.astype("datetime64[M]")

    # Issuances = demand. Receipts = restocking.
    pivot = (
        movements.pivot_table(
            index=["material_id", "period_month"],
            columns="movement_type",
            values="quantity",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    for col in ("ISSUANCE", "RECEIPT"):
        if col not in pivot.columns:
            pivot[col] = 0.0

    # Every material needs a row for every month, even a month with zero
    # movement — otherwise the lag features would silently skip a month.
    all_months = pd.date_range(
        movements["period_month"].min(),
        movements["period_month"].max(),
        freq="MS",
    )
    grid = pd.MultiIndex.from_product(
        [materials["material_id"], all_months],
        names=["material_id", "period_month"],
    ).to_frame(index=False)

    df = grid.merge(pivot, on=["material_id", "period_month"], how="left").fillna(0.0)
    df = df.rename(columns={"ISSUANCE": "demand_qty", "RECEIPT": "receipts"})
    df = df.sort_values(["material_id", "period_month"])

    # Running stock balance at the END of each month.
    df["net"] = df["receipts"] - df["demand_qty"]
    df["inventory_balance"] = df.groupby("material_id")["net"].cumsum()
    df["inventory_balance"] = df["inventory_balance"].clip(lower=0)

    df = df.merge(
        materials[["material_id", "unit_cost"]], on="material_id", how="left"
    )
    df["unit_cost"] = df["unit_cost"].astype(float)
    df["inventory_value"] = df["inventory_balance"] * df["unit_cost"]

    # Transaction volume per month (company-wide business activity).
    if not transactions.empty:
        transactions["txn_date"] = pd.to_datetime(transactions["txn_date"])
        txn = (
            transactions.assign(
                period_month=transactions["txn_date"].values.astype("datetime64[M]")
            )
            .groupby("period_month")
            .size()
            .rename("transaction_volume")
            .reset_index()
        )
        df = df.merge(txn, on="period_month", how="left")
    df["transaction_volume"] = df.get("transaction_volume", 0)
    df["transaction_volume"] = df["transaction_volume"].fillna(0).astype(int)

    # Projects active in each month.
    df["active_projects"] = 0
    if not projects.empty:
        projects["start_date"] = pd.to_datetime(projects["start_date"])
        projects["end_date"] = pd.to_datetime(projects["end_date"])
        counts = {}
        for m in all_months:
            m_end = m + pd.offsets.MonthEnd(0)
            live = (
                (projects["start_date"] <= m_end)
                & (projects["end_date"].isna() | (projects["end_date"] >= m))
            )
            counts[m] = int(live.sum())
        df["active_projects"] = df["period_month"].map(counts).fillna(0).astype(int)

    # Persist to D4.
    for r in df.itertuples(index=False):
        execute_query(
            db_config,
            """
            INSERT INTO monthly_demand
                (material_id, period_month, demand_qty, transaction_volume,
                 inventory_balance, inventory_value, active_projects)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (material_id, period_month) DO UPDATE SET
                demand_qty         = EXCLUDED.demand_qty,
                transaction_volume = EXCLUDED.transaction_volume,
                inventory_balance  = EXCLUDED.inventory_balance,
                inventory_value    = EXCLUDED.inventory_value,
                active_projects    = EXCLUDED.active_projects;
            """,
            (
                int(r.material_id),
                r.period_month.date(),
                float(r.demand_qty),
                int(r.transaction_volume),
                float(r.inventory_balance),
                float(r.inventory_value),
                int(r.active_projects),
            ),
        )

    log_audit(db_config, "AGGREGATE_MONTHLY_DEMAND",
              f"Rebuilt {len(df)} monthly rows across {len(materials)} materials.")
    return len(df)


# =================================================================
#  DFD 4.1 — Preprocess Forecast Data
# =================================================================
def load_monthly_dataset(db_config):
    rows = execute_query(
        db_config,
        """
        SELECT md.material_id, m.material_name, m.unit, m.unit_cost,
               md.period_month, md.demand_qty, md.transaction_volume,
               md.inventory_balance, md.inventory_value, md.active_projects
        FROM monthly_demand md
        JOIN materials m ON m.material_id = md.material_id
        ORDER BY md.material_id, md.period_month;
        """,
        fetch=True,
    )
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(
            "monthly_demand is empty. Run aggregate_monthly_demand() first."
        )

    df["period_month"] = pd.to_datetime(df["period_month"])
    for c in ("demand_qty", "inventory_balance", "inventory_value", "unit_cost"):
        df[c] = df[c].astype(float)
    for c in ("transaction_volume", "active_projects"):
        df[c] = df[c].astype(int)
    return df


def build_features(df):
    """
    Lag the predictors so that every feature is knowable BEFORE the month
    being predicted. This is what keeps the model honest.
    """
    df = df.sort_values(["material_id", "period_month"]).copy()
    g = df.groupby("material_id")

    df["prev_demand"] = g["demand_qty"].shift(1)
    df["prev_demand_2"] = g["demand_qty"].shift(2)
    df["prev_txn_volume"] = g["transaction_volume"].shift(1)
    df["opening_stock"] = g["inventory_balance"].shift(1)
    df["opening_value"] = g["inventory_value"].shift(1)
    # active_projects is NOT lagged: the project schedule is known in
    # advance, so next month's project count is legitimately available.

    return df.dropna(subset=FEATURES)


def _design_matrix(df, columns=None):
    """Numeric features + one-hot material dummies (per-material baselines)."""
    dummies = pd.get_dummies(df["material_name"], prefix="mat")
    X = pd.concat([df[FEATURES].astype(float), dummies.astype(float)], axis=1)
    if columns is not None:
        X = X.reindex(columns=columns, fill_value=0.0)
    return X


def _mape(y_true, y_pred):
    """
    MAPE is undefined where actual demand is 0, so those months are
    excluded rather than silently producing infinity.
    """
    y_true = np.asarray(y_true, float)
    y_pred = np.asarray(y_pred, float)
    mask = y_true != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((y_true[mask] - y_pred[mask]) / y_true[mask])) * 100)


def _chronological_split(df, test_ratio=0.2):
    """
    Hold out the most recent months. Never shuffle time-series data —
    a random split would train on the future and score on the past.
    """
    months = sorted(df["period_month"].unique())
    n_test = max(1, int(round(len(months) * test_ratio)))
    n_test = min(n_test, len(months) - 1)
    test_months = set(months[-n_test:])
    train = df[~df["period_month"].isin(test_months)]
    test = df[df["period_month"].isin(test_months)]
    return train, test


# =================================================================
#  DFD 4.2 / 4.3 / 4.4 — Train, Evaluate, Forecast, Save
# =================================================================
def run_forecast(db_config, overrides=None, test_ratio=0.2, username="system"):
    """
    Train one pooled MLR across all materials, evaluate it out-of-sample,
    then forecast NEXT MONTH's demand for every material.

    `overrides` supports what-if planning, e.g. {"active_projects": 8}
    — "if we take on 8 projects next month, how much steel do we need?"
    That is exactly the material-requirements-planning support the
    documentation asks for.
    """
    df = build_features(load_monthly_dataset(db_config))

    if len(df) < MIN_TRAINING_ROWS:
        raise ValueError(
            f"Only {len(df)} usable monthly rows after lagging "
            f"(need at least {MIN_TRAINING_ROWS}). Add more history, "
            f"then re-run the aggregation."
        )

    train_df, test_df = _chronological_split(df, test_ratio)

    X_train = _design_matrix(train_df)
    columns = list(X_train.columns)
    y_train = train_df["demand_qty"].values

    model = LinearRegression()
    model.fit(X_train, y_train)

    # --- 4.3 Evaluate on months the model has never seen ---
    X_test = _design_matrix(test_df, columns)
    y_test = test_df["demand_qty"].values
    y_pred = model.predict(X_test)

    metrics = {
        "mae":  round(float(mean_absolute_error(y_test, y_pred)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(y_test, y_pred))), 3),
        "mape": (round(_mape(y_test, y_pred), 2)
                 if _mape(y_test, y_pred) is not None else None),
        "r2":   round(float(r2_score(y_test, y_pred)), 4),
        "train_rows": int(len(train_df)),
        "test_rows":  int(len(test_df)),
        "evaluation": "out-of-sample (chronological hold-out)",
    }

    execute_query(
        db_config,
        """INSERT INTO model_metrics
             (model_name, mae, rmse, mape, r2, train_rows, test_rows, features_used)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s);""",
        (MODEL_NAME, metrics["mae"], metrics["rmse"], metrics["mape"],
         metrics["r2"], metrics["train_rows"], metrics["test_rows"],
         ", ".join(FEATURES)),
    )

    # --- Forecast the next month for every material ---
    latest_month = df["period_month"].max()
    forecast_month = (latest_month + pd.offsets.MonthBegin(1)).normalize()

    # Projects already scheduled for the forecast month.
    fm_end = forecast_month + pd.offsets.MonthEnd(0)
    proj = execute_query(
        db_config,
        """SELECT COUNT(*) AS n FROM projects
           WHERE start_date <= %s
             AND (end_date IS NULL OR end_date >= %s);""",
        (fm_end.date(), forecast_month.date()),
        fetch=True,
    )
    scheduled_projects = int(proj[0]["n"]) if proj else 0

    full = load_monthly_dataset(db_config)

    # A count of zero is ambiguous: it could mean "the shop genuinely has no
    # work booked", or "nobody has entered next month's projects yet". Those
    # are very different, and silently treating the second as the first drags
    # every forecast down. If nothing is booked, carry the current workload
    # forward and say so, rather than quietly predicting a dead month.
    projects_source = "scheduled project records"
    if scheduled_projects == 0:
        latest_month_val = full["period_month"].max()
        carried = int(
            full.loc[full["period_month"] == latest_month_val, "active_projects"].max()
        )
        if carried > 0:
            scheduled_projects = carried
            projects_source = (
                "carried forward from the latest month "
                "(no projects booked yet for the forecast month)"
            )
    rows, forecasts = [], []

    for mid, grp in full.groupby("material_id"):
        grp = grp.sort_values("period_month")
        if len(grp) < 2:
            continue
        last, prev = grp.iloc[-1], grp.iloc[-2]

        row = {
            "material_id":   mid,
            "material_name": last["material_name"],
            "unit":          last["unit"],
            "prev_demand":     float(last["demand_qty"]),
            "prev_demand_2":   float(prev["demand_qty"]),
            "prev_txn_volume": float(last["transaction_volume"]),
            "opening_stock":   float(last["inventory_balance"]),
            "opening_value":   float(last["inventory_value"]),
            "active_projects": float(scheduled_projects),
        }
        if overrides:
            row.update({k: float(v) for k, v in overrides.items() if k in FEATURES})
        rows.append(row)

    if not rows:
        raise ValueError("Not enough history per material to build a forecast row.")

    next_df = pd.DataFrame(rows)
    X_next = _design_matrix(next_df, columns)
    preds = model.predict(X_next)

    for row, pred in zip(rows, preds):
        predicted = max(round(float(pred), 2), 0.0)   # demand can't be negative
        stock = row["opening_stock"]
        reorder = max(round(predicted - stock, 2), 0.0)

        execute_query(
            db_config,
            """INSERT INTO forecast_results
                 (material_id, forecast_month, predicted_demand, model_name)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (material_id, forecast_month, model_name) DO UPDATE SET
                 predicted_demand = EXCLUDED.predicted_demand,
                 generated_at     = CURRENT_TIMESTAMP;""",
            (int(row["material_id"]), forecast_month.date(), predicted, MODEL_NAME),
        )

        forecasts.append({
            "material_id":      int(row["material_id"]),
            "material_name":    row["material_name"],
            "unit":             row["unit"],
            "predicted_demand": predicted,
            "current_stock":    round(stock, 2),
            "reorder_qty":      reorder,
            "prev_demand":      round(row["prev_demand"], 2),
            "active_projects":  int(row["active_projects"]),
        })

    # MLR is interpretable — showing the coefficients is the whole reason
    # the documentation chose it over a black-box model.
    coefficients = {
        f: round(float(c), 4) for f, c in zip(columns, model.coef_) if f in FEATURES
    }

    log_audit(
        db_config, "RUN_FORECAST",
        f"{MODEL_NAME} for {forecast_month.date()}: "
        f"{len(forecasts)} materials, R2={metrics['r2']}, MAE={metrics['mae']}.",
        username,
    )

    return {
        "model":            MODEL_NAME,
        "forecast_month":   forecast_month.strftime("%B %Y"),
        "forecast_date":    str(forecast_month.date()),
        "metrics":          metrics,
        "coefficients":     coefficients,
        "intercept":        round(float(model.intercept_), 4),
        "features_used":    FEATURES,
        "active_projects":  scheduled_projects,
        "projects_source":  projects_source,
        "forecasts":        forecasts,
    }
