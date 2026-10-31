from datetime import datetime

from flask import Blueprint, jsonify, session, send_file

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import permission_required
from security import limiter
from reports_export import REPORT_BUILDERS, generate_pdf, generate_excel

bp = Blueprint("reports", __name__)


REPORT_FILE_SLUGS = {
    "inventory": "Inventory_Report", "customer": "Customer_Report",
    "project": "Project_Report", "transaction": "Transaction_Report",
    "stock-in": "Stock_In_Report", "stock-out": "Stock_Out_Report",
    "back-order": "Back_Order_Report", "forecast": "Forecast_Report",
}


REPORT_TITLE_KEYS = {
    "Inventory Report": "inventory", "Customer Report": "customer",
    "Project Report": "project", "Client Transaction Report": "transaction",
    "Stock In Report": "stock-in", "Stock Out Report": "stock-out",
    "Back Order Report": "back-order", "Demand Forecast Report": "forecast",
}


@bp.route("/api/reports/overview")
@permission_required("reports")
def api_reports_overview():
    import re as _re

    exported = execute_query(DB_CONFIG, """
        SELECT COUNT(*) AS n FROM audit_logs
        WHERE action = 'REPORT_EXPORTED'
          AND logged_at >= date_trunc('year', CURRENT_DATE);
    """, fetch=True)[0]["n"]

    inv_value = execute_query(DB_CONFIG, """
        SELECT COALESCE(SUM(current_stock * unit_cost), 0) AS v FROM materials;
    """, fetch=True)[0]["v"]

    rev = execute_query(DB_CONFIG, """
        WITH l AS (SELECT MAX(txn_date) AS d FROM transactions)
        SELECT l.d AS latest,
               COALESCE(SUM(t.amount) FILTER (
                   WHERE t.txn_date >= date_trunc('year', l.d)::date
                     AND t.txn_date <= l.d), 0) AS ytd,
               COALESCE(SUM(t.amount) FILTER (
                   WHERE t.txn_date >= (date_trunc('year', l.d) - interval '1 year')::date
                     AND t.txn_date <= (l.d - interval '1 year')::date), 0) AS prev
        FROM l LEFT JOIN transactions t ON TRUE
        GROUP BY l.d;
    """, fetch=True)
    latest = rev[0]["latest"] if rev else None
    ytd = float(rev[0]["ytd"]) if rev else 0.0
    prev = float(rev[0]["prev"]) if rev else 0.0
    growth = round((ytd - prev) / prev * 100) if prev > 0 else None
    ytd_label = (f"Jan–{latest.strftime('%b')} {latest.year}" if latest
                 else "No transactions yet")

    months = execute_query(DB_CONFIG, """
        WITH l AS (SELECT date_trunc('month', MAX(txn_date)::timestamp) AS m FROM transactions)
        SELECT to_char(g, 'Mon') AS label, COALESCE(SUM(t.amount), 0) AS amt
        FROM l,
             generate_series(l.m - interval '5 months', l.m, interval '1 month') AS g
        LEFT JOIN transactions t ON date_trunc('month', t.txn_date::timestamp) = g
        GROUP BY g ORDER BY g;
    """, fetch=True)

    cats = execute_query(DB_CONFIG, """
        SELECT COALESCE(NULLIF(category, ''), 'Uncategorized') AS cat,
               SUM(current_stock * unit_cost) AS val
        FROM materials
        GROUP BY 1 HAVING SUM(current_stock * unit_cost) > 0
        ORDER BY val DESC;
    """, fetch=True)

    recent_rows = execute_query(DB_CONFIG, """
        SELECT a.log_id, a.details, a.logged_at,
               COALESCE(u.full_name, a.username, 'System') AS by_name
        FROM audit_logs a LEFT JOIN users u ON u.username = a.username
        WHERE a.action = 'REPORT_EXPORTED'
        ORDER BY a.log_id DESC LIMIT 8;
    """, fetch=True)
    recent = []
    for r in recent_rows:
        m = _re.match(r"^(.*) exported as (PDF|Excel)\.?$", r["details"] or "")
        title, fmt = (m.group(1), m.group(2)) if m else (r["details"] or "Report", "")
        recent.append({
            "ref": f"RPT-{r['log_id']:04d}", "type": title, "by": r["by_name"],
            "date": r["logged_at"].strftime("%Y-%m-%d") if r["logged_at"] else "",
            "format": fmt, "key": REPORT_TITLE_KEYS.get(title, ""),
        })

    return jsonify({"ok": True, "data": {
        "exportedThisYear": int(exported),
        "ytdRevenue": ytd, "ytdLabel": ytd_label,
        "inventoryValue": float(inv_value),
        "growthPct": growth,
        "revenueByMonth": [{"label": r["label"], "amount": float(r["amt"])} for r in months],
        "valueByCategory": [{"label": r["cat"], "value": float(r["val"])} for r in cats],
        "recent": recent,
    }})


@bp.route("/api/reports/<key>/data")
@permission_required("reports")
@limiter.limit("30 per minute")
def api_report_data(key):
    builder = REPORT_BUILDERS.get(key)
    if not builder:
        return jsonify({"ok": False, "error": "Unknown report type."}), 404
    title, subtitle, columns, rows = builder(DB_CONFIG)
    return jsonify({"ok": True, "data": {
        "title": title, "subtitle": subtitle, "columns": columns, "rows": rows,
    }})


@bp.route("/api/reports/<key>/pdf")
@permission_required("reports")
@limiter.limit("15 per minute")
def api_report_pdf(key):
    builder = REPORT_BUILDERS.get(key)
    if not builder:
        return jsonify({"ok": False, "error": "Unknown report type."}), 404
    title, subtitle, columns, rows = builder(DB_CONFIG)
    buf = generate_pdf(title, subtitle, columns, rows,
                       generated_by=session["user"]["name"])
    log_audit(DB_CONFIG, "REPORT_EXPORTED", f"{title} exported as PDF.",
              session["user"]["username"])
    fname = f"{REPORT_FILE_SLUGS.get(key, 'Report')}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name=fname)


@bp.route("/api/reports/<key>/excel")
@permission_required("reports")
@limiter.limit("15 per minute")
def api_report_excel(key):
    builder = REPORT_BUILDERS.get(key)
    if not builder:
        return jsonify({"ok": False, "error": "Unknown report type."}), 404
    title, subtitle, columns, rows = builder(DB_CONFIG)
    buf = generate_excel(title, subtitle, columns, rows,
                         generated_by=session["user"]["name"])
    log_audit(DB_CONFIG, "REPORT_EXPORTED", f"{title} exported as Excel.",
              session["user"]["username"])
    fname = f"{REPORT_FILE_SLUGS.get(key, 'Report')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     as_attachment=True, download_name=fname)
