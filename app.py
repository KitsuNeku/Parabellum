"""
Parabellum ISOS - Flask backend
=================================================================
    app.py         <- you are here
    config.py      <- database credentials + session secret key
    auth.py         <- login, sessions, role enforcement
    mlr_model.py   <- MONTHLY material demand forecasting (MLR)
    seed_data.py   <- generates 30 months of sample operational data
    seed_users.py  <- creates demo accounts (run once)
    schema.sql     <- run in pgAdmin first
    templates/     <- the 12 HTML pages
    static/        <- css/, js/, assets/

Reminder: "/api/..." are URLs, not folders. Never create an api/ directory.

Setup order:
    1. pgAdmin: run schema.sql
    2. python seed_users.py
    3. python seed_data.py
    4. python app.py   ->  http://127.0.0.1:5000
"""

from flask import Flask, render_template, jsonify, request, session, redirect, url_for
from datetime import datetime, timezone
import os
import psycopg2.errors

from config import DB_CONFIG, SECRET_KEY, DEBUG, AUTO_RETRAIN_ENABLED, AUTO_RETRAIN_HOUR, AUTO_AGGREGATE_BEFORE_RETRAIN
from mlr_model import aggregate_monthly_demand, get_materials, run_forecast, execute_query, log_audit, get_forecast_history, generate_sql_backup, restore_sql_backup
import weather_api
import requests
import scheduler as retrain_scheduler
from auth import (verify_login, login_required, permission_required,
                  ROLE_PERMISSIONS, ROLE_NAMES, ALL_PERMISSIONS, resolve_permissions,
                  get_role_permissions, hash_password)
from security import apply_security


def _allowed_pages():
    """Pages the signed-in user may open. Prefers the per-user resolved set
    stored at login time (honors any Settings > Users > Access override);
    falls back to role defaults for sessions established before that field
    existed."""
    u = session.get("user") or {}
    session_allowed = u.get("allowed_pages")
    return set(session_allowed) if session_allowed else ROLE_PERMISSIONS.get(u.get("role"), set())


def _out_of_stock_count():
    """Live number behind the red badge on the sidebar's Inventory link.
    Counted from the materials table on every page render, so the badge is
    never a hardcoded or sample figure. Returns 0 if the database can't be
    reached - a missing badge is better than a failed page."""
    try:
        rows = execute_query(DB_CONFIG,
                             "SELECT COUNT(*) AS n FROM materials WHERE current_stock <= 0;",
                             fetch=True)
        return int(rows[0]["n"]) if rows else 0
    except Exception:
        return 0


def _user_context():
    """Signed-in user + resolved page access, rendered server-side to avoid an identity flash."""
    u = session.get("user") or {}
    name = u.get("name", "")
    initials = "".join(w[0] for w in name.split()).upper()[:2] if name else "?"
    allowed = _allowed_pages()
    return {
        "current_user": u,
        "current_user_initials": initials,
        "allowed_pages": allowed,
        "inventory_oos_count": _out_of_stock_count() if "inventory" in allowed else 0,
    }

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ProxyFix: makes Flask trust X-Forwarded-For / X-Forwarded-Proto from a
# reverse proxy in front of this app (nginx, Caddy, Cloudflare, a hosting
# platform's load balancer). Without this, EVERY request looks like it
# came from the proxy's own IP -- which silently breaks two things that
# matter for security: per-IP rate limiting (every user shares one
# limit) and the IP address recorded in audit_logs (useless for
# incident investigation if it's always the proxy).
#
# OPT-IN ON PURPOSE: trusting X-Forwarded-For when there is NO real
# reverse proxy in front lets any client set that header themselves and
# spoof an arbitrary IP -- trivially bypassing rate limits and forging
# what shows up in the audit trail. Only set TRUST_PROXY=1 when you have
# confirmed a reverse proxy (not the raw internet) is the only thing
# that can reach this Flask process directly.
if os.getenv("TRUST_PROXY", "0") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    # x_for=1, x_proto=1: trust exactly ONE hop of X-Forwarded-For /
    # X-Forwarded-Proto (i.e. exactly one reverse proxy between the
    # client and this app). Raise these only if you deliberately chain
    # more than one proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

# Apply defense-in-depth measures - headers, rate limiting, request size
# caps, session hygiene. See security.py for the full list and honest
# scope caveats (what this covers and what needs infrastructure).
limiter = apply_security(app)

# Session cookie hardening:
# HTTPONLY - JavaScript cannot read the cookie, so a successful XSS
# injection still can't steal the session.
# SAMESITE - the cookie is not sent on cross-site requests, which
# blocks most CSRF attempts against session-based actions.
# SECURE - only sent over HTTPS. Defaults to off for local
# http://127.0.0.1 development. Set the SESSION_COOKIE_SECURE
# environment variable to "1" once the app is served over
# real HTTPS (e.g. behind nginx/Caddy with a certificate, or
# a host that terminates TLS for you) - the cookie will then
# refuse to be sent over a plain HTTP connection at all.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=1800,  # auto sign-out after 30 idle minutes
)

PAGES = ["dashboard", "inventory", "suppliers", "customers", "projects", "transactions",
         "forecasting", "reports", "settings", "profile"]


# ---------------- Public routes ----------------
@app.route("/")
def index():
    return render_template("index.html")       # public landing page


@app.route("/login")
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


# ---------------- Protected page routes ----------------
# Every module page requires a signed-in session. Forecasting is further
# restricted to the roles that ROLE_PERMISSIONS actually grants it to,
# matching the sidebar visibility rules - but enforced server-side, so
# the restriction is real and not just a hidden link.
def _make_page(name, permission=None):
    if permission:
        @permission_required(permission)
        def view():
            return render_template(f"{name}.html", **_user_context())
    else:
        @login_required
        def view():
            return render_template(f"{name}.html", **_user_context())
    view.__name__ = name
    return view


for _p in PAGES:
    # Every page name is a valid ROLE_PERMISSIONS key (dashboard/profile are
    # granted to all roles, so this is a no-op for them - but customers,
    # projects, transactions, etc. are now actually blocked server-side for
    # roles that don't have them, not just hidden from the sidebar.
    app.add_url_rule(f"/{_p}", _p, _make_page(_p, permission=_p))


# ---------------- Auth API ----------------
@app.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour")
def api_login():
    """
    The account-lockout in auth.py stops brute force against a SINGLE
    account. This per-IP limit stops "credential stuffing" where an
    attacker tries thousands of username/password pairs from one machine.
    """
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400

    user, error = verify_login(DB_CONFIG, username, password)
    if error:
        return jsonify({"ok": False, "error": error}), 401

    session.clear()
    session["user"] = user
    session["login_at"] = datetime.now(timezone.utc).isoformat()
    session.permanent = True
    return jsonify({"ok": True, "data": user})


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def api_me():
    """The frontend calls this on page load to know who is signed in,
    instead of trusting a hardcoded value in the page's JavaScript."""
    if "user" not in session:
        return jsonify({"ok": False, "error": "Not signed in."}), 401
    return jsonify({"ok": True, "data": session["user"]})


# ---------------- Data API ----------------
@app.route("/api/dashboard")
@login_required
def api_dashboard():
    """
    Real dashboard figures, queried from the database (DFD 5.0).
    Replaces the hardcoded counts the page shows on first paint.

    Returns the KPI counts, the 5 most recent transactions, the current
    forecast alert, and 6 months of material-usage totals for the chart -
    all from the actual tables, so "compare displayed totals with stored
    records" (admin test Table 1) passes.
    """
    try:
        def scalar(query, params=None):
            rows = execute_query(DB_CONFIG, query, params, fetch=True)
            return list(rows[0].values())[0] if rows else 0

        # --- KPI counts ---
        active_projects = scalar(
            "SELECT COUNT(*) FROM projects WHERE status = 'Ongoing';")
        total_items = scalar("SELECT COUNT(*) FROM materials;")
        # Same rule as _inv_status() / the Inventory page: Low Stock means
        # in stock but AT or below the reorder level. Out-of-stock items
        # (qty 0) are a separate status and are NOT counted here - the old
        # "current_stock < reorder_level" counted them AND missed items
        # sitting exactly at their reorder level, so this card disagreed
        # with the Low Stock list in the modal it opens.
        low_stock = scalar(
            "SELECT COUNT(*) FROM materials "
            "WHERE current_stock > 0 AND current_stock <= reorder_level;")

        # Transactions in the most recent month that has any records.
        monthly_txns = scalar("""
            SELECT COUNT(*) FROM transactions
            WHERE date_trunc('month', txn_date) = (
                SELECT date_trunc('month', MAX(txn_date)) FROM transactions
            );
        """)
        # The month those transactions belong to, so the card's caption is
        # real (it used to be a hardcoded "June 2026"). Empty if there are
        # no transactions at all.
        month_rows = execute_query(DB_CONFIG, """
            SELECT to_char(MAX(txn_date), 'FMMonth YYYY') AS label FROM transactions;
        """, fetch=True)
        monthly_label = (month_rows[0]["label"] if month_rows and month_rows[0]["label"] else "")

        # --- Recent transactions (join customer name) ---
        recent = execute_query(DB_CONFIG, """
            SELECT t.transaction_id, t.customer_name, t.amount, t.txn_date,
                   p.status AS project_status
            FROM transactions t
            LEFT JOIN projects p ON p.project_id = t.project_id
            ORDER BY t.txn_date DESC, t.transaction_id DESC
            LIMIT 5;
        """, fetch=True)

        recent_list = [{
            "inv": f"TXN-{r['transaction_id']:04d}",
            "cust": r["customer_name"] or "—",
            "total": float(r["amount"]) if r["amount"] is not None else 0.0,
            "date": str(r["txn_date"]),
            # A simple, defensible status derived from the linked project.
            "pay": "Paid" if (r["project_status"] == "Completed") else "Pending",
        } for r in recent] if "transactions" in _allowed_pages() else []   # client transactions are only for accounts with that page

        # --- Latest forecast alert (top reorder need) ---
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
            alert = {
                "material": r["material_name"],
                "pct": pct,
                "reorder": reorder,
                "unit": r["unit"],
            }

        # --- Material usage: total issuances per month, last 6 months ---
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

        # Daily (last 7 days) and weekly (last 6 weeks) totals for the
        # chart's Daily / Weekly toggle. These used to be hardcoded sample
        # arrays in data.js - the toggle only ever showed made-up numbers.
        # generate_series guarantees a bar for every day/week even when
        # nothing was issued, so a quiet day shows as 0, not a missing bar.
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

    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Notifications API (the bell in the top bar) ----------------
@app.route("/api/notifications")
@login_required
def api_notifications():
    """
    Live notification feed, built from the real tables - never a fixed list.
    Every page used to carry the same 5 hardcoded alerts ("Low stock: GI
    Sheet Corrugated 0.5mm - 8 minutes ago" ...) whatever the database held.

    What it reports, limited to modules the signed-in user can open:
      - Materials that are out of stock / at or below reorder level (inventory)
      - The most recent forecast run (forecasting)
      - The latest client transactions (transactions)
    Stock alerts are CURRENT conditions, so they carry the current quantity
    instead of a made-up "x minutes ago".
    """
    try:
        allowed = _allowed_pages()
        items = []

        if "inventory" in allowed:
            rows = execute_query(DB_CONFIG, """
                SELECT material_name, unit, current_stock, reorder_level
                FROM materials
                WHERE current_stock <= reorder_level
                ORDER BY (current_stock > 0), current_stock, material_name
                LIMIT 6;
            """, fetch=True)
            for r in rows:
                qty, reorder = float(r["current_stock"]), float(r["reorder_level"])
                if qty <= 0:
                    items.append({"ic": "bi-x-octagon-fill", "tone": "b-danger",
                                  "title": f"Out of stock: {r['material_name']}",
                                  "time": f"Reorder level {reorder:g} {r['unit']}"})
                else:
                    items.append({"ic": "bi-exclamation-triangle-fill", "tone": "b-danger",
                                  "title": f"Low stock: {r['material_name']}",
                                  "time": f"{qty:g} {r['unit']} left (reorder at {reorder:g})"})

        if "forecasting" in allowed:
            rows = execute_query(DB_CONFIG, """
                SELECT logged_at FROM audit_logs
                WHERE action IN ('RUN_FORECAST', 'SCHEDULED_RETRAIN')
                ORDER BY log_id DESC LIMIT 1;
            """, fetch=True)
            if rows and rows[0]["logged_at"]:
                items.append({"ic": "bi-graph-up-arrow", "tone": "b-info",
                              "title": "Forecast completed",
                              "time": rows[0]["logged_at"].strftime("%b %d, %Y %H:%M")})

        if "transactions" in allowed:
            rows = execute_query(DB_CONFIG, """
                SELECT transaction_id, customer_name, payment_status, txn_date
                FROM transactions
                ORDER BY txn_date DESC, transaction_id DESC LIMIT 3;
            """, fetch=True)
            for r in rows:
                status = r["payment_status"] or "Pending"
                customer = r["customer_name"] or "—"   # hoisted: no backslashes inside f-string {} before Python 3.12
                items.append({"ic": "bi-receipt",
                              "tone": "b-success" if status == "Paid" else "b-info",
                              "title": f"Transaction TXN-{r['transaction_id']:04d} · {customer} · {status}",
                              "time": r["txn_date"].strftime("%b %d, %Y") if r["txn_date"] else ""})

        return jsonify({"ok": True, "data": {"items": items, "count": len(items)}})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Profile API (My Profile page) ----------------
@app.route("/api/profile")
@login_required
def api_profile():
    """
    The signed-in user's own details, activity counts and recent actions,
    all read from the users and audit_logs tables. The Profile page used to
    show a fixed email (admin@parabellumsteel.com.ph, even to non-admins), a
    fixed phone/department, "248 Logins / 86 Reports / 12 Forecasts" and a
    made-up activity log.
    """
    try:
        uid = session["user"]["user_id"]
        username = session["user"]["username"]

        rows = execute_query(DB_CONFIG, """
            SELECT user_id, username, full_name, email, department, role
            FROM users WHERE user_id = %s;
        """, (uid,), fetch=True)
        if not rows:
            return jsonify({"ok": False, "error": "Account not found."}), 404
        u = rows[0]

        counts = execute_query(DB_CONFIG, """
            SELECT COUNT(*) FILTER (WHERE action = 'LOGIN_SUCCESS')   AS logins,
                   COUNT(*) FILTER (WHERE action = 'REPORT_EXPORTED') AS reports,
                   COUNT(*) FILTER (WHERE action = 'RUN_FORECAST')    AS forecasts
            FROM audit_logs WHERE username = %s;
        """, (username,), fetch=True)[0]

        recent = execute_query(DB_CONFIG, """
            SELECT action, details, logged_at FROM audit_logs
            WHERE username = %s ORDER BY log_id DESC LIMIT 6;
        """, (username,), fetch=True)

        week = execute_query(DB_CONFIG, """
            SELECT to_char(d, 'Dy') AS label, COUNT(a.log_id) AS n
            FROM generate_series((CURRENT_DATE - 6)::timestamp, CURRENT_DATE::timestamp,
                                 interval '1 day') AS d
            LEFT JOIN audit_logs a
                   ON a.username = %s AND a.logged_at::date = d::date
            GROUP BY d ORDER BY d;
        """, (username,), fetch=True)

        return jsonify({"ok": True, "data": {
            "userCode": f"USR-{u['user_id']:02d}",
            "username": u["username"],
            "name": u["full_name"] or u["username"],
            "email": u["email"] or "",
            "department": u["department"] or "",
            "role": u["role"],
            "stats": {"logins": int(counts["logins"]), "reports": int(counts["reports"]),
                      "forecasts": int(counts["forecasts"])},
            "recent": [{
                "action": r["action"], "details": r["details"] or "",
                "time": r["logged_at"].strftime("%b %d, %Y %H:%M") if r["logged_at"] else "",
            } for r in recent],
            "week": [{"label": r["label"], "n": int(r["n"])} for r in week],
        }})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Inventory API ----------------
def _inv_status(qty, reorder):
    """Same rule as the frontend, computed server-side so KPIs always agree."""
    qty = float(qty)
    reorder = float(reorder)
    if qty <= 0:
        return "Out of Stock"
    if qty <= reorder:
        return "Low Stock"
    return "In Stock"


def _material_row(r):
    """Map a materials row into the exact shape the inventory page expects."""
    qty = float(r["current_stock"])
    reorder = float(r["reorder_level"])
    return {
        "id": r["material_code"],
        "name": r["material_name"],
        "cat": r["category"] or "Uncategorized",
        "sup": r["supplier"] or "",
        "qty": qty,
        "unit": r["unit"],
        "reorder": reorder,
        "price": float(r["unit_cost"]),
        "loc": r["location"] or "",
        "added": str(r["added_date"]) if r["added_date"] else "",
        "status": _inv_status(qty, reorder),
    }


@app.route("/api/inventory")
@permission_required("inventory")
def api_inventory():
    """Full material list (D2) in the frontend's shape."""
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT material_id, material_code, material_name, unit, unit_cost,
                   current_stock, reorder_level, category, supplier, location, added_date
            FROM materials ORDER BY material_name;
        """, fetch=True)
        return jsonify({"ok": True, "data": [_material_row(r) for r in rows]})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/save", methods=["POST"])
@permission_required("inventory")
def api_inventory_save():
    """Add a new material, or edit an existing one (edit_id = material_code)."""
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Item name is required."}), 400

    try:
        qty = float(d.get("qty") or 0)
        reorder = float(d.get("reorder") or 0)
        price = float(d.get("price") or 0)
        fields = (name, d.get("cat"), d.get("sup"), d.get("unit") or "pcs",
                  price, reorder, d.get("loc"))
        edit_id = d.get("edit_id")

        if not edit_id:
            # Guard against creating a second row for an item that already
            # exists under (near enough) the same name - e.g. from the Stock
            # In modal's "type a new item name" box, if someone types a name
            # that's a different case or has stray whitespace compared to an
            # existing item instead of picking it from the search dropdown.
            # Without this, the two rows silently split one item's stock
            # history across two material_ids, and nothing on screen would
            # tell you why the numbers stopped adding up.
            dup = execute_query(DB_CONFIG,
                "SELECT material_code FROM materials WHERE LOWER(TRIM(material_name)) = LOWER(TRIM(%s));",
                (name,), fetch=True)
            if dup:
                return jsonify({"ok": False, "error":
                    f"An item named \"{name}\" already exists ({dup[0]['material_code']}). "
                    "Search for it above and pick it from the list instead of typing the name again."}), 400

        if edit_id:
            execute_query(DB_CONFIG, """
                UPDATE materials SET material_name=%s, category=%s, supplier=%s,
                       unit=%s, unit_cost=%s, reorder_level=%s, location=%s,
                       current_stock=%s
                WHERE material_code=%s;
            """, fields + (qty, edit_id))
            log_audit(DB_CONFIG, "MATERIAL_UPDATED", f"Edited material {edit_id} ({name}).",
                      session["user"]["username"])
        else:
            # Generate a unique material_code.
            row = execute_query(DB_CONFIG,
                "SELECT COALESCE(MAX(material_id), 0) + 1 AS n FROM materials;", fetch=True)
            code = f"MAT-{row[0]['n']:04d}"
            new_row = execute_query(DB_CONFIG, """
                INSERT INTO materials
                    (material_code, material_name, category, supplier, unit,
                     unit_cost, reorder_level, location, current_stock, added_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)
                RETURNING material_id;
            """, (code, name, d.get("cat"), d.get("sup"), d.get("unit") or "pcs",
                  price, reorder, d.get("loc"), qty), fetch=True)
            log_audit(DB_CONFIG, "MATERIAL_ADDED", f"Added material {code} ({name}).",
                      session["user"]["username"])

            # A new item registered with stock on hand (e.g. from the Stock In
            # modal's "New Item" option) is itself a stock receipt, so it
            # needs its own RECEIPT row - otherwise this quantity would be
            # sitting in current_stock without ever appearing in the Stock In
            # table, the Stock Movement Summary, or the Stock In report. The
            # material's current_stock was already set to `qty` above, so
            # this only records the movement - it must NOT also add qty
            # again (that's what _apply_movement would do).
            if qty > 0 and new_row:
                execute_query(DB_CONFIG, """
                    INSERT INTO stock_movements
                        (material_id, movement_type, quantity, movement_date, remarks, recorded_by)
                    VALUES (%s, 'RECEIPT', %s, CURRENT_DATE, %s, %s);
                """, (new_row[0]["material_id"], qty, "Initial stock (new item)",
                      session["user"]["name"]))

        return jsonify({"ok": True, "code": edit_id or code})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


def _apply_movement(material_code, quantity, kind, remarks, project_id=None, recorded_by=None):
    """
    Record a Stock In / Stock Out movement and adjust the balance.

    kind = 'RECEIPT'  (stock in from supplier, increases balance), or
           'ISSUANCE' (stock out to project/customer, decreases balance).
    Back orders are a separate thing entirely now - see
    _record_back_order() below, which writes to its own back_orders
    table instead of stock_movements.

    For issuances this ENFORCES the non-negative-stock rule required by
    Objective 1.1 and test Table 2 - an over-issuance is rejected outright,
    not silently clamped to zero.

    recorded_by: display name of the logged-in user performing this action,
    stored alongside the movement so the Stock In / Stock Out tables can
    show who did it - independent of `remarks`, which describes the
    movement itself (a delivery note, a project reference), not the person.
    """
    rows = execute_query(DB_CONFIG,
        "SELECT material_id, material_name, unit, current_stock FROM materials WHERE material_code=%s;",
        (material_code,), fetch=True)
    if not rows:
        raise ValueError("That material was not found.")
    m = rows[0]
    balance = float(m["current_stock"])
    quantity = float(quantity)

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    if kind == "ISSUANCE" and quantity > balance:
        raise ValueError(
            f"Cannot issue {quantity:g} {m['unit']} — only {balance:g} in stock.")

    new_balance = balance - quantity if kind == "ISSUANCE" else balance + quantity

    execute_query(DB_CONFIG, """
        INSERT INTO stock_movements
            (material_id, movement_type, quantity, movement_date, project_id, remarks, recorded_by)
        VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, %s);
    """, (m["material_id"], kind, quantity, project_id, remarks, recorded_by))

    execute_query(DB_CONFIG,
        "UPDATE materials SET current_stock=%s WHERE material_id=%s;",
        (new_balance, m["material_id"]))

    return m["material_name"], new_balance


def _record_back_order(material_code, quantity, remarks, back_order_by=None, recorded_by=None, stock_out_ref=None):
    """
    Log a back order (material returned by a customer/project) in its own
    back_orders table. Unlike _apply_movement(), this never touches
    materials.current_stock by itself - that only happens later, if/when
    staff mark it "Replaced" via _set_back_order_disposition() below.

    Returns (material_name, back_order_id) - the id lets the frontend show
    a receipt for exactly this record without having to re-fetch and guess
    which row is new.
    """
    rows = execute_query(DB_CONFIG,
        "SELECT material_id, material_name FROM materials WHERE material_code=%s;",
        (material_code,), fetch=True)
    if not rows:
        raise ValueError("That material was not found.")
    m = rows[0]
    quantity = float(quantity)
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    result = execute_query(DB_CONFIG, """
        INSERT INTO back_orders
            (material_id, quantity, return_date, stock_out_ref, remarks, back_order_by, recorded_by)
        VALUES (%s, %s, CURRENT_DATE, %s, %s, %s, %s)
        RETURNING back_order_id;
    """, (m["material_id"], quantity, stock_out_ref or None, remarks, back_order_by or None, recorded_by), fetch=True)

    return m["material_name"], result[0]["back_order_id"]


def _set_back_order_disposition(back_order_id, disposition, replaced_qty=None,
                                 reimbursed_amount=None, notes=None):
    """
    Set (or clear) a back order's disposition and apply the stock change
    that goes with it:
      'Replaced' -> some or all of the returned units go back on the shelf:
                       ADD replaced_qty to materials.current_stock. Doesn't
                       have to equal the full quantity originally returned -
                       e.g. only 3 of 5 returned units were undamaged.
      'Reimbursed' or cleared (None) -> does NOT sit in stock: if this
                       record was previously restocked by some amount,
                       REMOVE that exact amount again (reversing the
                       earlier add), clamped at 0 so a disposition change
                       can never push stock negative.

    back_orders.restocked_qty tracks exactly how much of this row's
    quantity is CURRENTLY included in current_stock (restocked mirrors
    whether that's > 0), so switching dispositions back and forth always
    reverses precisely what was actually added - never double-counted,
    and never dependent on replaced_qty staying the same across edits.

    replaced_qty is required (and must be > 0 and <= the original returned
    quantity) when disposition is 'Replaced'; reimbursed_amount is required
    (and must be > 0) when disposition is 'Reimbursed'. Both are ignored
    (stored as NULL) for any other disposition. notes is optional free text
    describing the disposition itself (condition on return, how the refund
    was paid, etc.), separate from the back order's original return reason.

    Returns (material_name, new_balance_or_None, stock_delta) for the
    audit log; stock_delta is 0 if nothing about current_stock changed.
    """
    rows = execute_query(DB_CONFIG, """
        SELECT bo.material_id, bo.quantity, bo.restocked_qty, m.material_name, m.current_stock, m.unit
          FROM back_orders bo JOIN materials m ON m.material_id = bo.material_id
         WHERE bo.back_order_id = %s;
    """, (back_order_id,), fetch=True)
    if not rows:
        raise ValueError("Back order record not found.")
    row = rows[0]
    quantity = float(row["quantity"])
    balance = float(row["current_stock"])
    old_restocked_qty = float(row["restocked_qty"] or 0)

    if disposition == "Replaced":
        if replaced_qty is None or replaced_qty <= 0:
            raise ValueError("Qty Replaced must be greater than zero.")
        if replaced_qty > quantity:
            raise ValueError(f"Qty Replaced can't exceed the {quantity:g} {row['unit']} returned.")
        new_restocked_qty = replaced_qty
    else:
        new_restocked_qty = 0.0
        replaced_qty = None   # never stored against a non-Replaced row

    if disposition != "Reimbursed":
        reimbursed_amount = None   # never stored against a non-Reimbursed row
    elif reimbursed_amount is None or reimbursed_amount <= 0:
        raise ValueError("Amount Reimbursed must be greater than zero.")

    stock_delta = new_restocked_qty - old_restocked_qty
    new_balance = balance + stock_delta
    if new_balance < 0:
        stock_delta = -balance
        new_balance = 0.0

    if stock_delta != 0.0:
        execute_query(DB_CONFIG,
            "UPDATE materials SET current_stock=%s WHERE material_id=%s;",
            (new_balance, row["material_id"]))

    execute_query(DB_CONFIG, """
        UPDATE back_orders
           SET disposition=%s, restocked=%s, restocked_qty=%s,
               replaced_qty=%s, reimbursed_amount=%s, disposition_notes=%s
         WHERE back_order_id=%s;
    """, (disposition, new_restocked_qty > 0, new_restocked_qty,
          replaced_qty, reimbursed_amount, notes, back_order_id))

    return row["material_name"], new_balance, stock_delta


@app.route("/api/inventory/stock-in", methods=["POST"])
@permission_required("inventory")
def api_stock_in():
    d = request.get_json(silent=True) or {}
    try:
        name, bal = _apply_movement(d.get("itemId"), d.get("qty"), "RECEIPT",
                                    d.get("remarks") or "Stock received",
                                    recorded_by=session["user"]["name"])
        log_audit(DB_CONFIG, "STOCK_IN", f"+{d.get('qty')} to {name} (now {bal:g}).",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/stock-out", methods=["POST"])
@permission_required("inventory")
def api_stock_out():
    d = request.get_json(silent=True) or {}
    try:
        name, bal = _apply_movement(d.get("itemId"), d.get("qty"), "ISSUANCE",
                                    d.get("ref") or "Material issued",
                                    recorded_by=session["user"]["name"])
        log_audit(DB_CONFIG, "STOCK_OUT", f"-{d.get('qty')} from {name} (now {bal:g}).",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except ValueError as e:
        # This is where the negative-stock guard reports back to the user.
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/return", methods=["POST"])
@permission_required("inventory")
def api_inventory_return():
    """
    Record a back-order return: material coming back from a customer or
    project. Logged in its own back_orders table (see _record_back_order),
    NOT in stock_movements - a back order is its own record type, not a
    Stock In or Stock Out. It does not change the material's on-hand
    current_stock by itself; that only happens later if staff mark it
    "Replaced" (see /api/inventory/return/disposition).
    """
    d = request.get_json(silent=True) or {}
    try:
        remarks = d.get("remarks") or ""
        customer = (d.get("customer") or "").strip()
        stock_out_ref = (d.get("stockOutRef") or "").strip()
        name, back_order_id = _record_back_order(d.get("itemId"), d.get("qty"), remarks,
                                    back_order_by=customer or None,
                                    recorded_by=session["user"]["name"],
                                    stock_out_ref=stock_out_ref or None)
        log_audit(DB_CONFIG, "STOCK_RETURN",
                  f"{d.get('qty')} of {name} logged as a back order (on-hand stock unchanged for now)."
                  + (f" Back-ordered by {customer}." if customer else ""),
                  session["user"]["username"])
        return jsonify({"ok": True, "backOrderId": back_order_id})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/return/disposition", methods=["POST"])
@permission_required("inventory")
def api_inventory_return_disposition():
    """
    Mark (or clear) what happened to a back-ordered item once it came
    back: 'Reimbursed' or 'Replaced'. Shown as a checkmark in the Back
    Orders table's Actions column, replacing the old View/Print/Delete
    icons there (those still apply to Stock In/Stock Out - this column
    is back-order-specific).

    Unlike before, this NOW changes materials.current_stock: marking a
    back order "Replaced" adds its replaced quantity back into stock (the
    item goes back on the shelf - not necessarily the full quantity
    returned, see "qty" below); "Reimbursed" does not. See
    _set_back_order_disposition() for exactly how that's applied -
    idempotently, so clicking the same checkmark twice (clearing it back
    to "not yet marked") or switching between the two options always
    applies the quantity exactly once in the right direction.

    Besides "disposition", the frontend's disposition popup sends:
      "qty"    - Qty Replaced (required, > 0, <= the original quantity
                 returned) when disposition is "Replaced".
      "amount" - Amount Reimbursed in pesos (required, > 0) when
                 disposition is "Reimbursed".
      "notes"  - optional free text about the disposition itself.
    Clearing a disposition (disposition omitted/empty) needs none of these.
    """
    d = request.get_json(silent=True) or {}
    back_order_id = d.get("backOrderId") or d.get("movementId")   # movementId kept for older clients
    disposition = (d.get("disposition") or "").strip() or None
    if disposition is not None and disposition not in ("Reimbursed", "Replaced"):
        return jsonify({"ok": False, "error": "Disposition must be 'Reimbursed' or 'Replaced'."}), 400

    replaced_qty = None
    reimbursed_amount = None
    if disposition == "Replaced":
        try:
            replaced_qty = float(d.get("qty"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Qty Replaced is required."}), 400
    elif disposition == "Reimbursed":
        try:
            reimbursed_amount = float(d.get("amount"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Amount Reimbursed is required."}), 400
    notes = (d.get("notes") or "").strip() or None

    try:
        name, new_balance, stock_delta = _set_back_order_disposition(
            back_order_id, disposition, replaced_qty=replaced_qty,
            reimbursed_amount=reimbursed_amount, notes=notes)
        if stock_delta > 0:
            stock_note = f" {stock_delta:g} added back to stock (now {new_balance:g})."
        elif stock_delta < 0:
            stock_note = f" {-stock_delta:g} removed from stock (now {new_balance:g})."
        else:
            stock_note = " Stock unchanged."
        log_audit(DB_CONFIG, "BACK_ORDER_DISPOSITION",
                  f"Back order BKO-{int(back_order_id):04d} ({name}) marked as {disposition or 'not yet marked'}.{stock_note}",
                  session["user"]["username"])
        return jsonify({"ok": True, "disposition": disposition or "", "newStock": new_balance})
    except ValueError as e:
        # _set_back_order_disposition raises ValueError both for "no such
        # record" (404 - the id itself is wrong) and for validation
        # failures like an out-of-range Qty Replaced (400 - the id is
        # fine, the submitted number isn't); its one "not found" message
        # is the only one that means the former.
        status = 404 if str(e) == "Back order record not found." else 400
        return jsonify({"ok": False, "error": str(e)}), status
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/summary")
@permission_required("inventory")
def api_inventory_summary():
    """
    Per-material aggregated totals: Total In (RECEIPT) and Total Out
    (ISSUANCE) from stock_movements, plus Back Orders from the separate
    back_orders table (material that came back from a customer/project).

    Net Stock = In - Out + Restocked Back Orders, which for any material
    with no manual adjustments equals the current on-hand quantity in
    materials.current_stock — surfacing the same number two ways is a
    quick reconciliation check for the person managing inventory.
    "Restocked" back orders are the ones marked "Replaced" - the only
    disposition that adds back into current_stock (see
    _set_back_order_disposition in app.py). "Reimbursed" back orders are
    included in backOrder (informational total) but not in netStock.
    """
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT m.material_code, m.material_name, m.category, m.unit,
                   m.current_stock,
                   COALESCE(sm.total_in, 0)  AS total_in,
                   COALESCE(sm.total_out, 0) AS total_out,
                   COALESCE(bo.total_return, 0)    AS total_return,
                   COALESCE(bo.total_restocked, 0) AS total_restocked
              FROM materials m
              LEFT JOIN (
                    SELECT material_id,
                           SUM(CASE WHEN movement_type = 'RECEIPT'  THEN quantity ELSE 0 END) AS total_in,
                           SUM(CASE WHEN movement_type = 'ISSUANCE' THEN quantity ELSE 0 END) AS total_out
                      FROM stock_movements
                     GROUP BY material_id
                   ) sm ON sm.material_id = m.material_id
              LEFT JOIN (
                    SELECT material_id,
                           SUM(quantity) AS total_return,
                           SUM(CASE WHEN restocked THEN quantity ELSE 0 END) AS total_restocked
                      FROM back_orders
                     GROUP BY material_id
                   ) bo ON bo.material_id = m.material_id
             ORDER BY m.material_code;
        """, fetch=True)
        data = [{
            "id":        r["material_code"],
            "name":      r["material_name"],
            "cat":       r["category"] or "Uncategorized",
            "unit":      r["unit"],
            "totalIn":   float(r["total_in"]),
            "totalOut":  float(r["total_out"]),
            "backOrder": float(r["total_return"]),
            "netStock":  float(r["total_in"]) - float(r["total_out"]) + float(r["total_restocked"]),
            "onHand":    float(r["current_stock"]),
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/delete", methods=["POST"])
@permission_required("inventory")
def api_inventory_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    try:
        # Remove dependent stock movements and back orders first (FK safety).
        execute_query(DB_CONFIG, """
            DELETE FROM stock_movements
            WHERE material_id = (SELECT material_id FROM materials WHERE material_code=%s);
        """, (code,))
        execute_query(DB_CONFIG, """
            DELETE FROM back_orders
            WHERE material_id = (SELECT material_id FROM materials WHERE material_code=%s);
        """, (code,))
        execute_query(DB_CONFIG, "DELETE FROM materials WHERE material_code=%s;", (code,))
        log_audit(DB_CONFIG, "MATERIAL_DELETED", f"Deleted material {code}.",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/movements")
@permission_required("inventory")
def api_inventory_movements():
    """
    Full Stock In / Stock Out movement history (RECEIPT and ISSUANCE
    only - back orders live in their own table now, see
    /api/inventory/backorders below), joined to each material's current
    code/name/unit, most recent first. The Inventory page splits this by
    `type` into its Stock In and Stock Out tables. `id` is the material's
    code, matching the same value used everywhere else on the page - so
    the existing Edit/Delete wiring (inventoryStore.find(id) /
    inventoryStore.remove(id)) works unchanged when those actions live on
    a movement row instead of a material-snapshot row.
    """
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT sm.movement_id, m.material_code, m.material_name, m.unit,
                   m.category, sm.movement_type, sm.quantity, sm.movement_date,
                   sm.remarks, sm.recorded_by
              FROM stock_movements sm
              JOIN materials m ON m.material_id = sm.material_id
             ORDER BY sm.movement_date DESC, sm.movement_id DESC;
        """, fetch=True)
        data = [{
            "id":         r["material_code"],
            "movementId": r["movement_id"],
            "name":       r["material_name"],
            "unit":       r["unit"],
            "cat":        r["category"] or "Uncategorized",
            "type":       r["movement_type"],   # 'RECEIPT' or 'ISSUANCE'
            "qty":        float(r["quantity"]),
            "date":       str(r["movement_date"]),
            "remarks":    r["remarks"] or "",
            "recordedBy": r["recorded_by"] or "\u2014",
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/backorders")
@permission_required("inventory")
def api_inventory_backorders():
    """
    Full back-order history, from its own back_orders table (NOT
    stock_movements - see the Back Orders redesign in schema.sql), joined
    to each material's current code/name/unit, most recent first. The
    Inventory page's Back Orders table and the Reports page's Back Order
    report both read this.

    `movementId` here is actually the back_order_id, kept under that key
    so the shared receipt/print/disposition JS (originally written for
    stock_movements rows) works unchanged against a back order row - the
    receipt itself is numbered "BKO-####" rather than "MOV-####" so the
    two id spaces are never confused (see buildReceiptHTML in app.js).
    """
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT bo.back_order_id, m.material_code, m.material_name, m.unit, m.category,
                   bo.quantity, bo.return_date, bo.stock_out_ref, bo.remarks,
                   bo.back_order_by, bo.recorded_by, bo.disposition, bo.restocked,
                   bo.restocked_qty, bo.replaced_qty, bo.reimbursed_amount, bo.disposition_notes
              FROM back_orders bo
              JOIN materials m ON m.material_id = bo.material_id
             ORDER BY bo.return_date DESC, bo.back_order_id DESC;
        """, fetch=True)
        data = [{
            "id":           r["material_code"],
            "movementId":   r["back_order_id"],
            "backOrderId":  r["back_order_id"],
            "name":         r["material_name"],
            "unit":         r["unit"],
            "cat":          r["category"] or "Uncategorized",
            "type":         "RETURN",
            "qty":          float(r["quantity"]),
            "date":         str(r["return_date"]),
            "stockOutRef":  r["stock_out_ref"] or "",
            "remarks":      r["remarks"] or "",
            "recordedBy":   r["recorded_by"] or "\u2014",
            "backOrderBy":  r["back_order_by"] or "",
            # 'Reimbursed', 'Replaced', or "" if not yet marked. Set via
            # /api/inventory/return/disposition, which also updates
            # restocked/restockedQty below.
            "disposition":  r["disposition"] or "",
            # True only while some of this row's quantity is currently
            # added into materials.current_stock (disposition = 'Replaced').
            "restocked":    bool(r["restocked"]),
            # How much of it, exactly - see restocked_qty in schema.sql.
            "restockedQty": float(r["restocked_qty"] or 0),
            # Set only while disposition = 'Replaced' / 'Reimbursed'
            # respectively; null otherwise. Entered via the disposition
            # popup (see backOrderActionBtns / openDispositionModal in
            # inventory.html).
            "replacedQty":      float(r["replaced_qty"]) if r["replaced_qty"] is not None else None,
            "reimbursedAmount": float(r["reimbursed_amount"]) if r["reimbursed_amount"] is not None else None,
            "dispositionNotes": r["disposition_notes"] or "",
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# Scoped list of projects + their client details, for the Stock Out Request
# modal on the Inventory page. Gated to "inventory" permission (NOT
# "projects"/"customers") so an Inventory Personnel role - who legitimately
# needs to issue stock against a project but isn't allowed to browse the
# projects or customers modules - can still populate the Project dropdown.
# Only the minimal fields the modal actually uses are returned.
@app.route("/api/inventory/projects-for-stockout")
@permission_required("inventory")
def api_inventory_projects_for_stockout():
    try:
        proj_rows = execute_query(DB_CONFIG, """
            SELECT p.project_code, p.project_name, p.status,
                   c.customer_code
              FROM projects p
              LEFT JOIN customers c ON c.customer_id = p.customer_id
             WHERE p.project_code IS NOT NULL
             ORDER BY p.start_date DESC;
        """, fetch=True)
        cust_rows = execute_query(DB_CONFIG, """
            SELECT c.customer_code, c.name, c.contact_person, c.phone, c.address
              FROM customers c
             ORDER BY c.name;
        """, fetch=True)
        status_map = {"Ongoing": "In Progress", "Completed": "Completed"}
        projects = [{
            "id": r["project_code"], "name": r["project_name"],
            "custId": r["customer_code"] or "",
            "status": status_map.get(r["status"], r["status"]),
        } for r in proj_rows]
        customers = [{
            "id": r["customer_code"], "name": r["name"],
            "contact": r["contact_person"] or "",
            "phone": r["phone"] or "",
            "addr": r["address"] or "",
        } for r in cust_rows]
        return jsonify({"ok": True, "projects": projects, "customers": customers})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Suppliers API ----------------
# Companies Parabellum buys materials from (Suppliers page). Kept as its
# own table rather than reusing materials.supplier (a free-text field
# that's been on Inventory since the start) - the frontend links a
# supplier to its materials by matching this table's `name` against each
# material's `sup` text, the same fallback the page's data.js already
# ships with, so existing inventory rows link up with no extra wiring.
@app.route("/api/suppliers")
@permission_required("suppliers")
def api_suppliers():
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT supplier_code, name, contact_person, phone, email, address,
                   category, terms, status, remarks, created_at
            FROM suppliers ORDER BY name;
        """, fetch=True)
        data = [{
            "id": r["supplier_code"], "name": r["name"],
            "contact": r["contact_person"] or "", "phone": r["phone"] or "",
            "email": r["email"] or "", "addr": r["address"] or "",
            "category": r["category"] or "", "terms": r["terms"] or "",
            "status": r["status"], "remarks": r["remarks"] or "",
            "dateAdded": str(r["created_at"].date()) if r["created_at"] else "",
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/suppliers/save", methods=["POST"])
@permission_required("suppliers")
def api_suppliers_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Company name is required."}), 400
    try:
        edit_id = d.get("edit_id")

        # Case-insensitive duplicate-name guard, same reasoning as the
        # one on /api/inventory/save: without it, two records for the
        # same actual supplier can silently exist (e.g. one typed with
        # different spacing/case), splitting its history across two rows.
        dup = execute_query(DB_CONFIG,
            "SELECT supplier_code FROM suppliers WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s)) AND supplier_code != COALESCE(%s, '');",
            (name, edit_id), fetch=True)
        if dup:
            return jsonify({"ok": False, "error":
                f"A supplier named \"{name}\" already exists ({dup[0]['supplier_code']})."}), 400

        fields = (name, d.get("contact"), d.get("phone"), d.get("email"),
                  d.get("addr"), d.get("category"), d.get("terms") or "Net 30",
                  d.get("status") or "Active", d.get("remarks"))
        if edit_id:
            execute_query(DB_CONFIG, """
                UPDATE suppliers SET name=%s, contact_person=%s, phone=%s, email=%s,
                       address=%s, category=%s, terms=%s, status=%s, remarks=%s
                WHERE supplier_code=%s;
            """, fields + (edit_id,))
            log_audit(DB_CONFIG, "SUPPLIER_UPDATED", f"Edited {edit_id} ({name}).",
                      session["user"]["username"])
        else:
            # The next code is "current max + 1", read and inserted as two
            # separate statements - not atomic. Two saves landing close
            # enough together (a double-click, or two people adding a
            # supplier at once) can both read the same max before either
            # has inserted, both compute the same code, and the second
            # INSERT then collides with the supplier_code unique
            # constraint. Retried here (new max, new code, try again)
            # rather than prevented outright, since nothing short of a
            # proper DB sequence fully closes that window - this just
            # makes the rare collision self-heal instead of surfacing as
            # a 500 error. The Add Supplier form also now disables its
            # Save button while a save is in flight, which stops the most
            # common cause (an actual double-click) before it gets here.
            code = None
            for attempt in range(5):
                row = execute_query(DB_CONFIG, """
                    SELECT COALESCE(MAX(CAST(SUBSTRING(supplier_code FROM 5) AS INTEGER)), 400) + 1 AS n
                    FROM suppliers WHERE supplier_code LIKE 'SUP-%';
                """, fetch=True)
                code = f"SUP-{row[0]['n']}"
                try:
                    execute_query(DB_CONFIG, """
                        INSERT INTO suppliers
                            (supplier_code, name, contact_person, phone, email, address,
                             category, terms, status, remarks)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """, (code,) + fields)
                    break
                except psycopg2.errors.UniqueViolation:
                    if attempt == 4:
                        raise
                    continue
            log_audit(DB_CONFIG, "SUPPLIER_ADDED", f"Added {code} ({name}).",
                      session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/suppliers/delete", methods=["POST"])
@permission_required("suppliers")
def api_suppliers_delete():
    # Not reachable from the Suppliers page itself (suppliers are
    # deactivated via /api/suppliers/save, never deleted, so Stock In
    # history always stays traceable) - kept only for API completeness
    # and admin/script use, matching the other entity-delete endpoints.
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    try:
        execute_query(DB_CONFIG, "DELETE FROM suppliers WHERE supplier_code=%s;", (code,))
        log_audit(DB_CONFIG, "SUPPLIER_DELETED", f"Deleted {code}.",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Customers API ----------------
@app.route("/api/customers")
@permission_required("customers")
def api_customers():
    """Customer list, with live project/transaction counts per customer."""
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT c.customer_code, c.name, c.contact_person, c.phone, c.email,
                   c.address, c.status,
                   (SELECT COUNT(*) FROM projects p WHERE p.customer_id = c.customer_id) AS projects,
                   (SELECT COUNT(*) FROM transactions t WHERE t.customer_id = c.customer_id) AS txns
            FROM customers c ORDER BY c.name;
        """, fetch=True)
        data = [{
            "id": r["customer_code"], "name": r["name"], "contact": r["contact_person"] or "",
            "phone": r["phone"] or "", "email": r["email"] or "", "addr": r["address"] or "",
            "projects": int(r["projects"]), "txns": int(r["txns"]), "status": r["status"],
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/customers/save", methods=["POST"])
@permission_required("customers")
def api_customers_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Customer name is required."}), 400
    try:
        fields = (name, d.get("contact"), d.get("phone"), d.get("email"),
                  d.get("addr"), d.get("status") or "Active")
        edit_id = d.get("edit_id")
        if edit_id:
            execute_query(DB_CONFIG, """
                UPDATE customers SET name=%s, contact_person=%s, phone=%s,
                       email=%s, address=%s, status=%s WHERE customer_code=%s;
            """, fields + (edit_id,))
            log_audit(DB_CONFIG, "CUSTOMER_UPDATED", f"Edited {edit_id} ({name}).",
                      session["user"]["username"])
        else:
            row = execute_query(DB_CONFIG, """
                SELECT COALESCE(MAX(CAST(SUBSTRING(customer_code FROM 5) AS INTEGER)), 200) + 1 AS n
                FROM customers WHERE customer_code LIKE 'CUS-%';
            """, fetch=True)
            code = f"CUS-{row[0]['n']}"
            execute_query(DB_CONFIG, """
                INSERT INTO customers
                    (customer_code, name, contact_person, phone, email, address, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (code,) + fields)
            log_audit(DB_CONFIG, "CUSTOMER_ADDED", f"Added {code} ({name}).",
                      session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/customers/delete", methods=["POST"])
@permission_required("customers")
def api_customers_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    try:
        # Don't orphan projects/transactions - just unlink them.
        execute_query(DB_CONFIG, """
            UPDATE projects SET customer_id = NULL
            WHERE customer_id = (SELECT customer_id FROM customers WHERE customer_code=%s);
        """, (code,))
        execute_query(DB_CONFIG, """
            UPDATE transactions SET customer_id = NULL
            WHERE customer_id = (SELECT customer_id FROM customers WHERE customer_code=%s);
        """, (code,))
        execute_query(DB_CONFIG, "DELETE FROM customers WHERE customer_code=%s;", (code,))
        log_audit(DB_CONFIG, "CUSTOMER_DELETED", f"Deleted {code}.",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Projects API ----------------
@app.route("/api/projects")
@permission_required("projects")
def api_projects():
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT p.project_code, p.project_name, p.status, p.budget, p.priority,
                   p.progress, p.staff, p.start_date, p.end_date,
                   c.customer_code, c.name AS customer_name,
                   e.name AS staff_name
            FROM projects p
            LEFT JOIN customers c ON c.customer_id = p.customer_id
            LEFT JOIN employees e ON e.employee_code = p.staff
            WHERE p.project_code IS NOT NULL
            ORDER BY p.start_date DESC;
        """, fetch=True)
        # Map DB status to the frontend's wording (Ongoing -> In Progress).
        status_map = {"Ongoing": "In Progress", "Completed": "Completed"}
        data = [{
            "id": r["project_code"], "name": r["project_name"],
            "custId": r["customer_code"] or "", "staffId": r["staff"] or "",
            # Display names resolved here, by the database, from the real
            # customers/employees rows. The page used to look these up in
            # hardcoded sample arrays (data.js), which would show the WRONG
            # name whenever a real customer's code matched a sample code.
            "cust": r["customer_name"] or "—",
            "staff": r["staff_name"] or r["staff"] or "—",
            "budget": float(r["budget"] or 0),
            "start": str(r["start_date"]) if r["start_date"] else "",
            "due": str(r["end_date"]) if r["end_date"] else "",
            "status": status_map.get(r["status"], r["status"]),
            "priority": r["priority"] or "Medium", "progress": int(r["progress"] or 0),
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/employees")
@permission_required("projects")
def api_employees():
    """Staff directory (the `employees` table) - fills the Projects page's
    "Assigned" dropdown. This used to be a hardcoded 5-person array in
    data.js that didn't match the database (which has a sixth employee and
    whatever else gets added)."""
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT employee_code, name, role, status
            FROM employees ORDER BY employee_code;
        """, fetch=True)
        return jsonify({"ok": True, "data": [{
            "id": r["employee_code"], "name": r["name"],
            "role": r["role"] or "", "status": r["status"] or "Active",
        } for r in rows]})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/projects/save", methods=["POST"])
@permission_required("projects")
def api_projects_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Project name is required."}), 400
    try:
        # Resolve customer code -> id, if provided.
        cust_id = None
        if d.get("custId"):
            crow = execute_query(DB_CONFIG,
                "SELECT customer_id FROM customers WHERE customer_code=%s;",
                (d.get("custId"),), fetch=True)
            cust_id = crow[0]["customer_id"] if crow else None

        # Frontend "In Progress" -> DB "Ongoing".
        status = "Ongoing" if d.get("status") in (None, "In Progress") else d.get("status")
        progress = int(d.get("progress") or 0)
        budget = float(d.get("budget") or 0)
        if budget < 0:
            return jsonify({"ok": False, "error": "Budget cannot be negative."}), 400
        if not (0 <= progress <= 100):
            return jsonify({"ok": False, "error": "Progress must be between 0 and 100."}), 400
        edit_id = d.get("edit_id")

        if edit_id:
            execute_query(DB_CONFIG, """
                UPDATE projects SET project_name=%s, customer_id=%s, staff=%s,
                       budget=%s, start_date=%s, end_date=%s, status=%s,
                       priority=%s, progress=%s
                WHERE project_code=%s;
            """, (name, cust_id, d.get("staffId"), budget, d.get("start") or None,
                  d.get("due") or None, status, d.get("priority") or "Medium",
                  progress, edit_id))
            log_audit(DB_CONFIG, "PROJECT_UPDATED", f"Edited {edit_id} ({name}).",
                      session["user"]["username"])
        else:
            row = execute_query(DB_CONFIG, """
                SELECT COALESCE(MAX(CAST(SUBSTRING(project_code FROM 5) AS INTEGER)), 300) + 1 AS n
                FROM projects WHERE project_code LIKE 'PRJ-%';
            """, fetch=True)
            code = f"PRJ-{row[0]['n']}"
            execute_query(DB_CONFIG, """
                INSERT INTO projects
                    (project_code, project_name, customer_id, staff, budget,
                     start_date, end_date, status, priority, progress)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (code, name, cust_id, d.get("staffId"), budget,
                  d.get("start") or None, d.get("due") or None, status,
                  d.get("priority") or "Medium", progress))
            log_audit(DB_CONFIG, "PROJECT_ADDED", f"Added {code} ({name}).",
                      session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/projects/delete", methods=["POST"])
@permission_required("projects")
def api_projects_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    try:
        execute_query(DB_CONFIG, """
            UPDATE transactions SET project_id = NULL
            WHERE project_id = (SELECT project_id FROM projects WHERE project_code=%s);
        """, (code,))
        execute_query(DB_CONFIG, "DELETE FROM projects WHERE project_code=%s;", (code,))
        log_audit(DB_CONFIG, "PROJECT_DELETED", f"Deleted {code}.",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Transactions API ----------------
@app.route("/api/transactions")
@permission_required("transactions")
def api_transactions():
    """Transaction list, joined to customer name + project code."""
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT t.transaction_id, t.material_name, t.quantity, t.unit_price,
                   t.payment_status, t.payment_method, t.txn_date,
                   c.customer_code, c.name AS customer_name, p.project_code
            FROM transactions t
            LEFT JOIN customers c ON c.customer_id = t.customer_id
            LEFT JOIN projects  p ON p.project_id  = t.project_id
            ORDER BY t.txn_date DESC, t.transaction_id DESC;
        """, fetch=True)
        data = [{
            "inv": f"TXN-{r['transaction_id']:04d}",
            "custId": r["customer_code"] or "",
            "cust": r["customer_name"] or "—",   # resolves the blank-customer bug
            "proj": r["project_code"] or "—",
            "material": r["material_name"] or "—",
            "qty": float(r["quantity"] or 0),
            "price": float(r["unit_price"] or 0),
            "pay": r["payment_status"] or "Pending",
            "method": r["payment_method"] or "",
            "date": str(r["txn_date"]) if r["txn_date"] else "",
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/transactions/save", methods=["POST"])
@permission_required("transactions")
def api_transactions_save():
    """
    Create a transaction AND deduct the sold material from inventory.

    This is Objective 1.3 - "monitor project-related material usage and
    connect usage records to inventory deductions." When a material with a
    known code/name is sold, we record an ISSUANCE stock movement and reduce
    the balance, enforcing the same non-negative-stock rule as Stock Out.
    """
    d = request.get_json(silent=True) or {}
    material_name = (d.get("material") or "").strip()
    if not material_name:
        return jsonify({"ok": False, "error": "Material is required."}), 400

    try:
        qty = float(d.get("qty") or 0)
        price = float(d.get("price") or 0)
        if qty <= 0:
            return jsonify({"ok": False, "error": "Quantity must be greater than zero."}), 400
        if price < 0:
            return jsonify({"ok": False, "error": "Unit price cannot be negative."}), 400

        # Resolve customer and project codes to ids.
        cust_id = None
        if d.get("custId"):
            r = execute_query(DB_CONFIG,
                "SELECT customer_id, name FROM customers WHERE customer_code=%s;",
                (d.get("custId"),), fetch=True)
            cust_id = r[0]["customer_id"] if r else None
        cust_name = r[0]["name"] if (d.get("custId") and r) else d.get("custId")

        proj_id = None
        if d.get("proj"):
            r = execute_query(DB_CONFIG,
                "SELECT project_id FROM projects WHERE project_code=%s;",
                (d.get("proj"),), fetch=True)
            proj_id = r[0]["project_id"] if r else None

        # If this material exists in the catalog, deduct it (Objective 1.3).
        mat = execute_query(DB_CONFIG,
            "SELECT material_id, current_stock, unit FROM materials WHERE material_name=%s;",
            (material_name,), fetch=True)
        if mat:
            m = mat[0]
            balance = float(m["current_stock"])
            if qty > balance:
                return jsonify({"ok": False,
                    "error": f"Cannot sell {qty:g} {m['unit']} of {material_name} — only {balance:g} in stock."}), 400
            execute_query(DB_CONFIG, """
                INSERT INTO stock_movements
                    (material_id, movement_type, quantity, movement_date, project_id, remarks)
                VALUES (%s, 'ISSUANCE', %s, CURRENT_DATE, %s, %s);
            """, (m["material_id"], qty, proj_id, "Sold via transaction"))
            execute_query(DB_CONFIG,
                "UPDATE materials SET current_stock = current_stock - %s WHERE material_id=%s;",
                (qty, m["material_id"]))

        # Record the transaction. amount = qty * price (kept for the dashboard/forecast).
        execute_query(DB_CONFIG, """
            INSERT INTO transactions
                (project_id, customer_id, customer_name, txn_date, amount,
                 material_name, quantity, unit_price, payment_status, payment_method)
            VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s);
        """, (proj_id, cust_id, cust_name, qty * price, material_name, qty, price,
              d.get("pay") or "Pending", d.get("method") or ""))

        log_audit(DB_CONFIG, "TRANSACTION_CREATED",
                  f"{material_name} x{qty:g} for {cust_name or 'walk-in'} "
                  f"({'stock deducted' if mat else 'no stock link'}).",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database or model error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- User Management API (Settings > Users) ----------------
@app.route("/api/users")
@permission_required("settings")
def api_users():
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT user_id, username, full_name, role, email, department,
                   is_active, custom_permissions
            FROM users ORDER BY full_name;
        """, fetch=True)
        live_role_perms = get_role_permissions(DB_CONFIG)
        data = []
        for r in rows:
            role_defaults = sorted(live_role_perms.get(r["role"], set()))
            resolved = sorted(resolve_permissions(r["role"], r["custom_permissions"], live_role_perms))
            data.append({
                "id":       f"USR-{r['user_id']:02d}",
                "username": r["username"],
                "name":     r["full_name"] or "",
                "role":     r["role"],
                "email":    r["email"] or "",
                "dept":     r["department"] or "",
                "status":   "Active" if r["is_active"] else "Suspended",
                # Access-override extras: the raw custom_permissions field
                # (NULL = not overridden), the effective permissions the
                # user actually sees, and the role's defaults for comparison.
                "customPermissions": r["custom_permissions"] or "",
                "hasOverride":       bool((r["custom_permissions"] or "").strip()),
                "effectivePermissions": resolved,
                "rolePermissions":      role_defaults,
            })
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/users/permissions", methods=["POST"])
@permission_required("settings")
def api_users_permissions():
    """
    Set (or clear) a per-user access override. Body:
      { "id": "USR-02", "permissions": ["dashboard","inventory","profile"] }
        → sets custom_permissions to the given comma-joined list
      { "id": "USR-02", "reset": true }
        → clears custom_permissions (NULL) so role defaults apply again

    Safeguards:
    - The permission set is intersected with ALL_PERMISSIONS so a bad
      value can't grant something invalid.
    - Non-admins can never be given the "settings" key by an override.
    - An admin cannot remove their OWN settings access here — that would
      lock them out of this very page. Change the role first if the
      intent is really to demote themselves.
    """
    d = request.get_json(silent=True) or {}
    edit_id = d.get("id") or ""
    reset = bool(d.get("reset"))
    perms = d.get("permissions") or []
    if not edit_id.startswith("USR-"):
        return jsonify({"ok": False, "error": "Invalid user id."}), 400
    try:
        user_id = int(edit_id.split("-")[1])
    except (ValueError, IndexError):
        return jsonify({"ok": False, "error": "Invalid user id."}), 400

    try:
        rows = execute_query(
            DB_CONFIG,
            "SELECT username, role FROM users WHERE user_id = %s;",
            (user_id,), fetch=True,
        )
        if not rows:
            return jsonify({"ok": False, "error": "User not found."}), 404
        target = rows[0]

        if reset:
            new_value = None
            log_detail = f"Cleared custom permissions for {target['username']} — role defaults now apply."
        else:
            cleaned = {str(p).strip() for p in perms if isinstance(p, str) and p.strip()}
            cleaned &= ALL_PERMISSIONS
            if target["role"] != "System Administrator":
                cleaned.discard("settings")

            # Self-lockout guard: an admin editing their own record must
            # keep the "settings" key, otherwise they can't come back here
            # to fix it.
            me = session["user"]
            if me.get("user_id") == user_id and "settings" not in cleaned:
                return jsonify({
                    "ok": False,
                    "error": "You can't take away your own Settings access — you would be locked out of this page.",
                }), 400

            # Order the CSV for stable, human-readable rows in the DB.
            # Uses the master PAGES list so no page can be silently dropped
            # (this used to be a hand-typed list that left out "suppliers",
            # so every Apply quietly removed Supplier access).
            new_value = ",".join(p for p in PAGES if p in cleaned)
            log_detail = (f"Set custom permissions for {target['username']} "
                          f"to [{new_value or '(none)'}].")

        execute_query(
            DB_CONFIG,
            "UPDATE users SET custom_permissions = %s WHERE user_id = %s;",
            (new_value, user_id),
        )
        log_audit(DB_CONFIG, "USER_PERMISSIONS_CHANGED", log_detail,
                  session["user"]["username"])

        # If the admin just edited THEIR OWN record, refresh their session
        # so the sidebar and permission checks reflect the new set on the
        # next click, instead of waiting until they sign out and back in.
        if session["user"].get("user_id") == user_id:
            session["user"]["allowed_pages"] = sorted(
                resolve_permissions(target["role"], new_value, get_role_permissions(DB_CONFIG))
            )
            session.modified = True

        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Role default permissions API (Settings > Roles & Permissions) ----------------
@app.route("/api/roles/permissions")
@permission_required("settings")
def api_roles_permissions():
    """Current role-default matrix, for rendering the clickable grid."""
    try:
        live = get_role_permissions(DB_CONFIG)
        data = {role: sorted(perms) for role, perms in live.items()}
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/roles/permissions/toggle", methods=["POST"])
@permission_required("settings")
def api_roles_permissions_toggle():
    """
    Flip one cell of the Roles & Permissions matrix. Body:
      { "role": "Inventory Personnel", "module": "customers", "enabled": true }

    Safeguards (mirror the per-user Access override's rules):
    - "settings" can only ever belong to System Administrator - granting
      it to any other role is rejected, and it can never be removed FROM
      System Administrator (that would mean no one could ever reach this
      page again to fix it).
    - A role can't be left with zero modules - that would silently lock
      out everyone currently on that role.
    - Users already signed in keep their current session's access until
      they next log in (same as a per-user Access edit), so this never
      kicks anyone out mid-session.
    """
    d = request.get_json(silent=True) or {}
    role = d.get("role") or ""
    module = d.get("module") or ""
    enabled = bool(d.get("enabled"))

    if role not in ROLE_NAMES:
        return jsonify({"ok": False, "error": "Invalid role."}), 400
    if module not in ALL_PERMISSIONS:
        return jsonify({"ok": False, "error": "Invalid module."}), 400
    if module == "settings" and enabled and role != "System Administrator":
        return jsonify({"ok": False, "error": "Only System Administrator can have Settings access."}), 400
    if module == "settings" and not enabled and role == "System Administrator":
        return jsonify({"ok": False, "error": "Settings access can't be removed from System Administrator — that would lock everyone out of this page."}), 400

    try:
        rows = execute_query(
            DB_CONFIG, "SELECT permissions FROM role_permissions WHERE role = %s;",
            (role,), fetch=True,
        )
        current = {p.strip() for p in (rows[0]["permissions"] or "").split(",") if p.strip()} if rows else set()

        if enabled:
            current.add(module)
        else:
            current.discard(module)

        if not current:
            return jsonify({"ok": False, "error": f"{role} can't be left with zero modules."}), 400

        new_value = ",".join(p for p in PAGES if p in current)

        execute_query(DB_CONFIG, """
            INSERT INTO role_permissions (role, permissions) VALUES (%s, %s)
            ON CONFLICT (role) DO UPDATE SET permissions = EXCLUDED.permissions;
        """, (role, new_value))

        log_audit(DB_CONFIG, "ROLE_PERMISSIONS_CHANGED",
                  f"{'Granted' if enabled else 'Revoked'} '{module}' {'to' if enabled else 'from'} "
                  f"{role} (now: [{new_value}]).", session["user"]["username"])

        return jsonify({"ok": True, "data": sorted(current)})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/users/save", methods=["POST"])
@permission_required("settings")
def api_users_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    username = (d.get("username") or "").strip()
    role = d.get("role") or ""
    email = (d.get("email") or "").strip()
    if not name or not username:
        return jsonify({"ok": False, "error": "Name and username are required."}), 400
    if role not in ROLE_NAMES:
        return jsonify({"ok": False, "error": "Invalid role."}), 400

    edit_id = d.get("edit_id")  # e.g. "USR-02"
    is_active = d.get("status", "Active") != "Suspended"
    password = d.get("password") or ""

    try:
        if edit_id:
            user_id = int(edit_id.split("-")[1])
            if password:
                execute_query(DB_CONFIG, """
                    UPDATE users SET full_name=%s, username=%s, role=%s, email=%s,
                           department=%s, is_active=%s, password_hash=%s
                    WHERE user_id=%s;
                """, (name, username, role, email, d.get("dept"), is_active,
                      hash_password(password), user_id))
            else:
                execute_query(DB_CONFIG, """
                    UPDATE users SET full_name=%s, username=%s, role=%s, email=%s,
                           department=%s, is_active=%s
                    WHERE user_id=%s;
                """, (name, username, role, email, d.get("dept"), is_active, user_id))
            log_audit(DB_CONFIG, "USER_UPDATED", f"Edited {username} ({role}).",
                      session["user"]["username"])
        else:
            if not password:
                return jsonify({"ok": False, "error": "A password is required for new accounts."}), 400
            execute_query(DB_CONFIG, """
                INSERT INTO users (username, password_hash, full_name, role, email, department, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (username, hash_password(password), name, role, email, d.get("dept"), is_active))
            log_audit(DB_CONFIG, "USER_CREATED", f"Created {username} ({role}).",
                      session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        # A duplicate username is the one case worth a specific message -
        # everything else stays generic per the no-internal-detail rule.
        msg = ("That username is already taken." if "UNIQUE" in str(e).upper()
               or "unique" in str(e).lower() else
               "A server error occurred. Please try again or contact your administrator.")
        return jsonify({"ok": False, "error": msg}), 500


@app.route("/api/users/deactivate", methods=["POST"])
@permission_required("settings")
def api_users_deactivate():
    """
    Soft-delete only - never hard-deletes an account, since that would
    orphan its audit_logs history (who did what, historically, would lose
    its "who"). Also blocks deactivating your own currently-logged-in
    account, a classic footgun that would otherwise lock you out with no
    other admin able to fix it except by editing the database directly.
    """
    d = request.get_json(silent=True) or {}
    edit_id = d.get("id") or ""
    try:
        user_id = int(edit_id.split("-")[1])
    except (ValueError, IndexError):
        return jsonify({"ok": False, "error": "Invalid user id."}), 400

    if user_id == session["user"]["user_id"]:
        return jsonify({"ok": False, "error": "You cannot deactivate your own account."}), 400

    try:
        execute_query(DB_CONFIG, "UPDATE users SET is_active=FALSE WHERE user_id=%s;", (user_id,))
        log_audit(DB_CONFIG, "USER_DEACTIVATED", f"Deactivated user_id {user_id}.",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Backup API (Settings > Backup & Restore) ----------------
@app.route("/api/settings/backup")
@permission_required("settings")
def api_settings_backup():
    """
    Returns the full database backup as plain-text SQL in the JSON body
    (base64-free - it's plain SQL text, safe as JSON string). The
    frontend does NOT navigate to this URL or use an <a download> link -
    that would just drop the file in the browser's Downloads folder.
    Instead it fetches this, then uses the File System Access API to
    let the person pick a real folder on their computer and writes the
    file there themselves, which is the actual "local backup" this
    button promises.
    """
    try:
        sql_text = generate_sql_backup(DB_CONFIG)
        filename = f"parabellum_backup_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}.sql"
        log_audit(DB_CONFIG, "BACKUP_CREATED", f"Generated backup file {filename}.",
                  session["user"]["username"])
        return jsonify({"ok": True, "filename": filename, "sql": sql_text})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/settings/restore", methods=["POST"])
@permission_required("settings")
def api_settings_restore():
    """
    Loads an uploaded .sql backup file (the same format /api/settings/backup
    generates) back into the database, replacing the current data in every
    table that backup covers. This is destructive and cannot be undone from
    inside the app, so on top of needing "settings" access it's restricted
    to the System Administrator role specifically -- the frontend also
    makes the person confirm through a dedicated dialog before this is ever
    called, but that's a UI convenience, not the real guard.
    """
    if session["user"]["role"] != "System Administrator":
        return jsonify({"ok": False, "error": "Only a System Administrator can restore a backup."}), 403

    data = request.get_json(silent=True) or {}
    sql_text = (data.get("sql") or "").strip()
    filename = data.get("filename") or "uploaded backup"

    if not sql_text:
        return jsonify({"ok": False, "error": "No file content was received. Please choose a .sql backup file and try again."}), 400

    try:
        restore_sql_backup(DB_CONFIG, sql_text)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "Restore failed partway through, so the database was left unchanged. Please check that this is a genuine Parabellum backup file and try again, or contact your administrator."}), 500

    # audit_logs itself was just truncated and reloaded as part of the
    # restore, so this is the first row logged into the restored table --
    # recording it now (not before) is what makes it survive.
    signed_in_user_id = session["user"]["user_id"]
    signed_in_username = session["user"]["username"]
    try:
        log_audit(DB_CONFIG, "DATABASE_RESTORED", f"Restored database from {filename}.",
                  signed_in_username)
    except Exception:
        pass

    # The restored data may not include the account that's currently signed
    # in at all (a backup from before that account existed), or that
    # username/user_id may now belong to someone else, or their role/
    # permissions may have changed in the restored data - in any of those
    # cases the session can no longer be trusted, so it's cleared and
    # everyone is sent back to login. But when the exact same account (same
    # user_id AND username) is still present and active in what was just
    # restored, there's nothing stale about the session - rebuild it from
    # the restored row (picking up any role/permission changes the restore
    # brought with it) and let the admin carry on without being bounced out
    # for no real reason.
    stayed_signed_in = False
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT user_id, username, full_name, role, is_active, custom_permissions
            FROM users WHERE user_id = %s AND username = %s;
        """, (signed_in_user_id, signed_in_username), fetch=True)
        u = rows[0] if rows else None
        if u and u["is_active"]:
            session["user"] = {
                "user_id": u["user_id"],
                "username": u["username"],
                "name": u["full_name"] or u["username"],
                "role": u["role"],
                "allowed_pages": sorted(resolve_permissions(
                    u["role"], u.get("custom_permissions"), get_role_permissions(DB_CONFIG))),
            }
            stayed_signed_in = True
    except Exception:
        app.logger.exception("Could not re-check the signed-in account after restore")

    if not stayed_signed_in:
        session.clear()
    return jsonify({"ok": True, "stayed_signed_in": stayed_signed_in})


# ---------------- System Logs / Audit Trail API (Settings > Logs) ----------------
@app.route("/api/audit-logs")
@permission_required("settings")
def api_audit_logs():
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT username, action, details, logged_at
            FROM audit_logs ORDER BY log_id DESC LIMIT 100;
        """, fetch=True)
        data = [{
            "time": str(r["logged_at"])[:16] if r["logged_at"] else "",
            "user": r["username"] or "System", "action": r["details"] or r["action"],
            "module": r["action"],
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Profile avatar upload ----------------
import os as _os
from werkzeug.utils import secure_filename

ALLOWED_AVATAR_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
AVATAR_DIR = _os.path.join(app.root_path, "static", "uploads", "avatars")

# Magic-byte signatures for the allowed types. An extension check alone
# only looks at the filename the client CLAIMS -- nothing stops someone
# from uploading arbitrary content (an HTML/JS payload, an executable)
# with a ".png" name. Checking the actual file header closes that gap:
# the browser/OS still trusts the file's real content type, not its name.
_AVATAR_MAGIC_BYTES = {
    "png":  [b"\x89PNG\r\n\x1a\n"],
    "jpg":  [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif":  [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],   # WEBP also needs "WEBP" at bytes 8-12, checked below
}


def _content_matches_extension(file_storage, ext):
    """Read a small header chunk and check it against the claimed extension's
    magic bytes. Restores the file's read position afterward so .save() still
    works. Returns True only if the content genuinely looks like that type."""
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if not header:
        return False
    signatures = _AVATAR_MAGIC_BYTES.get(ext, [])
    if not any(header.startswith(sig) for sig in signatures):
        return False
    if ext == "webp":
        # RIFF is a generic container; confirm the WEBP fourcc too.
        return len(header) >= 12 and header[8:12] == b"WEBP"
    return True


@app.route("/api/profile/avatar", methods=["POST"])
@login_required
def api_profile_avatar():
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file received."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_AVATAR_EXTS:
        return jsonify({"ok": False, "error": "Only PNG, JPG, GIF, or WEBP images are allowed."}), 400

    if not _content_matches_extension(file, ext):
        log_audit(DB_CONFIG, "AVATAR_REJECTED",
                  f"Uploaded file's content did not match its .{ext} extension.",
                  session.get("user", {}).get("username", "unknown"))
        return jsonify({"ok": False, "error": "That file doesn't look like a valid image. Please upload a real PNG, JPG, GIF, or WEBP."}), 400

    # Flask already caps the whole request body at MAX_CONTENT_LENGTH (see
    # security.py) - this just gives a clearer, specific error message for
    # this endpoint instead of the generic 413 page.
    file.seek(0, _os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 3 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image must be under 3 MB."}), 400

    try:
        _os.makedirs(AVATAR_DIR, exist_ok=True)
        user_id = session["user"]["user_id"]
        fname = secure_filename(f"user_{user_id}.{ext}")
        # Remove any previous avatar in a different format for this user.
        for old_ext in ALLOWED_AVATAR_EXTS:
            old_path = _os.path.join(AVATAR_DIR, f"user_{user_id}.{old_ext}")
            if _os.path.exists(old_path) and old_ext != ext:
                _os.remove(old_path)
        file.save(_os.path.join(AVATAR_DIR, fname))

        url = url_for("static", filename=f"uploads/avatars/{fname}")
        execute_query(DB_CONFIG, "UPDATE users SET avatar_path=%s WHERE user_id=%s;",
                     (url, user_id))
        session["user"]["avatar_path"] = url   # so it shows immediately, no re-login needed
        log_audit(DB_CONFIG, "AVATAR_UPDATED", "Profile photo updated.",
                  session["user"]["username"])
        return jsonify({"ok": True, "url": url})
    except Exception as e:
        app.logger.exception("File upload error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Reports API ----------------
from flask import send_file
from reports_export import REPORT_BUILDERS, generate_pdf, generate_excel

REPORT_FILE_SLUGS = {
    "inventory": "Inventory_Report", "customer": "Customer_Report",
    "project": "Project_Report", "transaction": "Transaction_Report",
    "stock-in": "Stock_In_Report", "stock-out": "Stock_Out_Report",
    "back-order": "Back_Order_Report", "forecast": "Forecast_Report",
}


# Report title (as stored in the audit trail's "<title> exported as PDF.")
# -> the report key the export routes use. Lets the "Recent Reports" table
# offer a working re-download for each row it lists.
REPORT_TITLE_KEYS = {
    "Inventory Report": "inventory", "Customer Report": "customer",
    "Project Report": "project", "Client Transaction Report": "transaction",
    "Stock In Report": "stock-in", "Stock Out Report": "stock-out",
    "Back Order Report": "back-order", "Demand Forecast Report": "forecast",
}


@app.route("/api/reports/overview")
@permission_required("reports")
def api_reports_overview():
    """
    Everything the Reports page shows ABOVE the generator, from the real
    tables: the four headline cards, the Monthly Revenue and Inventory by
    Category charts, and the Recent Reports list. All of it used to be
    hardcoded ("124 reports", "YTD Revenue P13.6M", a fixed Jan-Jun revenue
    series, a made-up category pie, and five invented report rows).

    "Year to date" is measured against the year of the LATEST transaction
    on record (the same convention /api/dashboard uses for its monthly
    count), so it stays meaningful whatever dates the data carries.
    """
    try:
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
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/reports/<key>/data")
@permission_required("reports")
@limiter.limit("30 per minute")
def api_report_data(key):
    """
    Structured report data for the on-screen preview modal. Same builder
    function that the PDF and Excel routes use - the three formats can
    never show different numbers from each other.
    """
    builder = REPORT_BUILDERS.get(key)
    if not builder:
        return jsonify({"ok": False, "error": "Unknown report type."}), 404
    try:
        title, subtitle, columns, rows = builder(DB_CONFIG)
        return jsonify({"ok": True, "data": {
            "title": title, "subtitle": subtitle, "columns": columns, "rows": rows,
        }})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/reports/<key>/pdf")
@permission_required("reports")
@limiter.limit("15 per minute")
def api_report_pdf(key):
    builder = REPORT_BUILDERS.get(key)
    if not builder:
        return jsonify({"ok": False, "error": "Unknown report type."}), 404
    try:
        title, subtitle, columns, rows = builder(DB_CONFIG)
        buf = generate_pdf(title, subtitle, columns, rows,
                           generated_by=session["user"]["name"])
        log_audit(DB_CONFIG, "REPORT_EXPORTED", f"{title} exported as PDF.",
                  session["user"]["username"])
        fname = f"{REPORT_FILE_SLUGS.get(key, 'Report')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        return send_file(buf, mimetype="application/pdf",
                         as_attachment=True, download_name=fname)
    except Exception as e:
        app.logger.exception("Report generation error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/reports/<key>/excel")
@permission_required("reports")
@limiter.limit("15 per minute")
def api_report_excel(key):
    builder = REPORT_BUILDERS.get(key)
    if not builder:
        return jsonify({"ok": False, "error": "Unknown report type."}), 404
    try:
        title, subtitle, columns, rows = builder(DB_CONFIG)
        buf = generate_excel(title, subtitle, columns, rows,
                             generated_by=session["user"]["name"])
        log_audit(DB_CONFIG, "REPORT_EXPORTED", f"{title} exported as Excel.",
                  session["user"]["username"])
        fname = f"{REPORT_FILE_SLUGS.get(key, 'Report')}_{datetime.now().strftime('%Y%m%d')}.xlsx"
        return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                         as_attachment=True, download_name=fname)
    except Exception as e:
        app.logger.exception("Report generation error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/materials")
@permission_required("forecasting")
def api_materials():
    """Material master (D2) - fills the forecasting dropdown from the DB."""
    try:
        mats = get_materials(DB_CONFIG)
        for m in mats:
            for k, v in m.items():
                if hasattr(v, "is_integer") or type(v).__name__ == "Decimal":
                    m[k] = float(v)
        return jsonify({"ok": True, "data": mats})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/aggregate", methods=["POST"])
@permission_required("forecasting")
def api_aggregate():
    """DFD 3.2 - rebuild monthly_demand (D4) from raw operational records."""
    try:
        n = aggregate_monthly_demand(DB_CONFIG)
        return jsonify({"ok": True, "rows": n})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/forecast", methods=["POST"])
@permission_required("forecasting")
@limiter.limit("6 per minute")
def api_forecast():
    """
    DFD 4.1-4.4. Rebuilds monthly_demand, trains MLR, evaluates
    out-of-sample, forecasts NEXT MONTH for every material, saves to
    D5 + D6, and returns the results.

    Optional body: {"overrides": {"active_projects": 8}}  -> what-if planning
    """
    payload = request.get_json(silent=True) or {}
    overrides = payload.get("overrides") or None

    try:
        aggregate_monthly_demand(DB_CONFIG)
        # username= so the audit trail (and the Profile page's activity
        # log / forecast count) attributes the run to whoever triggered it,
        # instead of defaulting every run to "system".
        return jsonify({"ok": True, "data": run_forecast(
            DB_CONFIG, overrides=overrides, username=session["user"]["username"])})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database or model error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/forecast_history")
@permission_required("forecasting")
def api_forecast_history():
    """Past forecasts (D5) LEFT JOINed with actual demand (D4)."""
    try:
        rows = get_forecast_history(DB_CONFIG, limit=15)
        return jsonify({"ok": True, "data": rows})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/weather/sync", methods=["POST"])
@permission_required("forecasting")
@limiter.limit("6 per hour")
def api_weather_sync():
    """
    Sync historical weather for Lipa City from Open-Meteo into
    monthly_weather (D8). Deliberately separate from /api/forecast
    (external HTTPS, not on the hot path). Run once at setup, then
    periodically (daily/weekly cron).

    Optional body: {"start_date": "2023-01-01", "end_date": "2026-08-31"}
    """
    payload = request.get_json(silent=True) or {}
    start_date = payload.get("start_date") or weather_api.DEFAULT_START_DATE
    end_date = payload.get("end_date")
    try:
        n = weather_api.sync_weather_to_db(DB_CONFIG, start_date=start_date, end_date=end_date)
        return jsonify({"ok": True, "months_synced": n, "location": weather_api.LOCATION_NAME})
    except requests.exceptions.RequestException as e:
        app.logger.exception("Weather API request failed")
        return jsonify({"ok": False, "error": "Could not reach the weather service. Check your internet connection and try again."}), 502
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database error during weather sync")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/scheduler/status")
@permission_required("forecasting")
def api_scheduler_status():
    """
    Whether nightly auto-retraining is on, when it next fires, and how
    the last run went. Surface this on the forecasting page so a demo
    can point at it: "the system will retrain itself tonight without
    anyone touching it."
    """
    return jsonify({"ok": True, "data": retrain_scheduler.get_status()})


@app.route("/api/scheduler/retrain_now", methods=["POST"])
@permission_required("forecasting")
@limiter.limit("6 per hour")
def api_scheduler_retrain_now():
    """
    Manually fire the SAME job the nightly scheduler runs, on demand -
    useful for a live defense demo ("watch it retrain right now")
    without waiting for 2am. Distinct from POST /api/forecast only in
    that it goes through scheduler.run_once (so it updates the
    scheduler's last-run status and logs as SCHEDULED_RETRAIN rather
    than a plain manual run) and optionally re-aggregates first.
    """
    payload = request.get_json(silent=True) or {}
    also_aggregate = bool(payload.get("aggregate_first", False)) and AUTO_AGGREGATE_BEFORE_RETRAIN
    ok, message = retrain_scheduler.run_once(DB_CONFIG, auto_aggregate=also_aggregate)
    status_code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message}), status_code


if __name__ == "__main__":
    # Start the nightly auto-retrain scheduler exactly once. Flask's
    # debug-mode reloader spawns a child process and re-executes this
    # module in it - without this guard, debug mode would start TWO
    # competing schedulers. WERKZEUG_RUN_MAIN is only set in that child
    # process, so this correctly starts the scheduler once whether
    # DEBUG is on or off.
    if AUTO_RETRAIN_ENABLED and (not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
        retrain_scheduler.start(
            DB_CONFIG,
            hour=AUTO_RETRAIN_HOUR,
            auto_aggregate=AUTO_AGGREGATE_BEFORE_RETRAIN,
        )

    # debug=True must never be used once the app is reachable by anyone
    # other than you - it exposes an interactive code console on errors.
    app.run(host="0.0.0.0", port=5000, debug=DEBUG)
