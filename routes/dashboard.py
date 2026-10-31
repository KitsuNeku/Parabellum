from flask import Blueprint, jsonify, session

from config import DB_CONFIG
from db import execute_query
from auth import allowed_pages, login_required
import preferences
from routes import support

bp = Blueprint("dashboard", __name__)


@bp.route("/api/dashboard")
@login_required
def api_dashboard():
    def scalar(query, params=None):
        rows = execute_query(DB_CONFIG, query, params, fetch=True)
        return list(rows[0].values())[0] if rows else 0

    # KPI counts
    active_projects = scalar(
        "SELECT COUNT(*) FROM projects WHERE status = 'Ongoing';")
    total_items = scalar("SELECT COUNT(*) FROM materials;")
    low_stock = scalar(
        "SELECT COUNT(*) FROM materials "
        "WHERE current_stock > 0 AND current_stock <= reorder_level;")

    monthly_txns = scalar("""
        SELECT COUNT(*) FROM transactions
        WHERE date_trunc('month', txn_date) = (
            SELECT date_trunc('month', MAX(txn_date)) FROM transactions
        );
    """)
    month_rows = execute_query(DB_CONFIG, """
        SELECT to_char(MAX(txn_date), 'FMMonth YYYY') AS label FROM transactions;
    """, fetch=True)
    monthly_label = (month_rows[0]["label"] if month_rows and month_rows[0]["label"] else "")

    # Recent transactions (join customer name)
    recent = execute_query(DB_CONFIG, """
        SELECT t.transaction_id, t.customer_name, t.amount, t.txn_date, t.payment_status
        FROM transactions t
        ORDER BY t.txn_date DESC, t.transaction_id DESC
        LIMIT 5;
    """, fetch=True)

    recent_list = [{
        "inv": f"TXN-{r['transaction_id']:04d}",
        "cust": r["customer_name"] or "—",
        "total": float(r["amount"]) if r["amount"] is not None else 0.0,
        "date": str(r["txn_date"]),
        "pay": r["payment_status"] or "Pending",
    } for r in recent] if "transactions" in allowed_pages() else []

    alert = None
    fc = execute_query(DB_CONFIG, """
        SELECT m.material_name, m.unit, m.current_stock,
               f.predicted_demand, f.forecast_month
        FROM forecast_results f
        JOIN materials m ON m.material_id = f.material_id
        WHERE f.forecast_month = (SELECT MAX(forecast_month) FROM forecast_results)
        ORDER BY (f.predicted_demand - m.current_stock) DESC
        LIMIT 1;
    """, fetch=True)
    if fc:
        r = fc[0]
        predicted = float(r["predicted_demand"])
        stock = float(r["current_stock"])
        reorder = max(0, round(predicted - stock))
        prev = execute_query(DB_CONFIG, """
            SELECT demand_qty FROM monthly_demand md
            JOIN materials m ON m.material_id = md.material_id
            WHERE m.material_name = %s
            ORDER BY md.period_month DESC LIMIT 1;
        """, (r["material_name"],), fetch=True)
        prev_demand = float(prev[0]["demand_qty"]) if prev else 0
        pct = round((predicted - prev_demand) / prev_demand * 100) if prev_demand else 0
        alert = None if reorder <= 0 else {
            "material": r["material_name"],
            "pct": pct,
            "reorder": reorder,
            "predicted": round(predicted, 2),
            "stock": round(stock, 2),
            "unit": r["unit"],
            "month": r["forecast_month"].strftime("%B %Y") if r["forecast_month"] else "",
        }

    usage = execute_query(DB_CONFIG, """
        SELECT to_char(date_trunc('month', movement_date), 'Mon') AS label,
               date_trunc('month', movement_date) AS m,
               SUM(quantity) AS qty
        FROM stock_movements
        WHERE movement_type = 'ISSUANCE'
        GROUP BY date_trunc('month', movement_date)
        ORDER BY m DESC
        LIMIT 6;
    """, fetch=True)
    usage_list = [{"label": u["label"], "qty": float(u["qty"])}
                  for u in reversed(usage)]

    daily = execute_query(DB_CONFIG, """
        SELECT CASE WHEN d::date = CURRENT_DATE THEN 'Today' ELSE to_char(d, 'Dy') END AS label,
               COALESCE(SUM(sm.quantity), 0) AS qty
        FROM generate_series((CURRENT_DATE - 6)::timestamp, CURRENT_DATE::timestamp,
                             interval '1 day') AS d
        LEFT JOIN stock_movements sm
               ON sm.movement_type = 'ISSUANCE' AND sm.movement_date = d::date
        GROUP BY d ORDER BY d;
    """, fetch=True)
    daily_list = [{"label": r["label"], "qty": float(r["qty"])} for r in daily]

    weekly = execute_query(DB_CONFIG, """
        SELECT to_char(w, 'Mon FMDD') AS label, COALESCE(SUM(sm.quantity), 0) AS qty
        FROM generate_series((date_trunc('week', CURRENT_DATE) - interval '35 days')::timestamp,
                             date_trunc('week', CURRENT_DATE)::timestamp,
                             interval '7 days') AS w
        LEFT JOIN stock_movements sm
               ON sm.movement_type = 'ISSUANCE'
              AND sm.movement_date >= w::date AND sm.movement_date < w::date + 7
        GROUP BY w ORDER BY w;
    """, fetch=True)
    weekly_list = [{"label": r["label"], "qty": float(r["qty"])} for r in weekly]

    return jsonify({"ok": True, "data": {
        "kpi": {
            "activeProjects": int(active_projects),
            "monthlyTxns": int(monthly_txns),
            "monthlyLabel": monthly_label,
            "totalItems": int(total_items),
            "lowStock": int(low_stock),
        },
        "recent": recent_list,
        "alert": alert,
        "usage": usage_list,
        "usageDaily": daily_list,
        "usageWeekly": weekly_list,
    }})


@bp.route("/api/notifications")
@login_required
def api_notifications():
    allowed = allowed_pages()
    notify = preferences.load(DB_CONFIG, session["user"].get("user_id"))["notify"]
    items = []

    if ("inventory" in allowed or "outlook" in allowed) and notify["lowStock"]:
        rows = execute_query(DB_CONFIG, """
            SELECT material_name, unit, current_stock, reorder_level, critical_level
            FROM materials
            WHERE current_stock <= GREATEST(reorder_level, critical_level)
            ORDER BY (current_stock > 0),
                     (critical_level > 0 AND current_stock <= critical_level) DESC,
                     current_stock, material_name
            LIMIT 6;
        """, fetch=True)
        for r in rows:
            qty, reorder, critical = float(r["current_stock"]), float(r["reorder_level"]), float(r["critical_level"] or 0)
            if qty <= 0:
                items.append({"ic": "bi-x-octagon-fill", "tone": "b-danger",
                              "title": f"Out of stock: {r['material_name']}",
                              "time": f"Reorder level {reorder:g} {r['unit']}"})
            elif critical > 0 and qty <= critical:
                items.append({"ic": "bi-exclamation-octagon-fill", "tone": "b-danger",
                              "title": f"Critical stock: {r['material_name']}",
                              "time": f"{qty:g} {r['unit']} left (critical level {critical:g})"})
            else:
                items.append({"ic": "bi-exclamation-triangle-fill", "tone": "b-danger",
                              "title": f"Low stock: {r['material_name']}",
                              "time": f"{qty:g} {r['unit']} left (reorder at {reorder:g})"})
        standby = execute_query(DB_CONFIG, """
            SELECT COUNT(*) AS n FROM stock_movements
            WHERE movement_type = 'ISSUANCE' AND delivery_failed_at IS NOT NULL AND returned_at IS NULL;
        """, fetch=True)[0]["n"]
        if standby:
            items.append({"ic": "bi-truck", "tone": "b-warning",
                          "title": f"{standby} failed deliver{'y' if standby == 1 else 'ies'} on standby",
                          "time": "Re-deliver or return to inventory in Stock Outlook"})

    if "support" in allowed:
        n = support.unread_ticket_count()
        if n:
            items.append({"ic": "bi-headset", "tone": "b-info",
                          "title": f"{n} support ticket{'' if n == 1 else 's'} with new messages",
                          "time": "Open Customer Support to reply"})

    if "forecasting" in allowed and notify["forecast"]:
        rows = execute_query(DB_CONFIG, """
            SELECT logged_at FROM audit_logs
            WHERE action IN ('RUN_FORECAST', 'SCHEDULED_RETRAIN')
            ORDER BY log_id DESC LIMIT 1;
        """, fetch=True)
        if rows and rows[0]["logged_at"]:
            items.append({"ic": "bi-graph-up-arrow", "tone": "b-info",
                          "title": "Forecast completed",
                          "time": rows[0]["logged_at"].strftime("%b %d, %Y %H:%M")})

    if "transactions" in allowed and notify["transactions"]:
        rows = execute_query(DB_CONFIG, """
            SELECT transaction_id, customer_name, payment_status, txn_date
            FROM transactions
            ORDER BY txn_date DESC, transaction_id DESC LIMIT 3;
        """, fetch=True)
        for r in rows:
            status = r["payment_status"] or "Pending"
            customer = r["customer_name"] or "—"
            items.append({"ic": "bi-receipt",
                          "tone": "b-success" if status == "Paid" else "b-info",
                          "title": f"Transaction TXN-{r['transaction_id']:04d} · {customer} · {status}",
                          "time": r["txn_date"].strftime("%b %d, %Y") if r["txn_date"] else ""})

    return jsonify({"ok": True, "data": {"items": items, "count": len(items)}})
