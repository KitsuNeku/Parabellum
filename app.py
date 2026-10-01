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

from config import DB_CONFIG, SECRET_KEY, DEBUG, AUTO_RETRAIN_ENABLED, AUTO_RETRAIN_HOUR, AUTO_AGGREGATE_BEFORE_RETRAIN
from mlr_model import aggregate_monthly_demand, get_materials, run_forecast, execute_query, log_audit, get_forecast_history, generate_sql_backup, restore_sql_backup
import weather_api
import requests
import scheduler as retrain_scheduler
from auth import (verify_login, login_required, permission_required,
                  ROLE_PERMISSIONS, ROLE_NAMES, ALL_PERMISSIONS, resolve_permissions,
                  get_role_permissions, hash_password)
from security import apply_security


def _user_context():
    """Signed-in user + resolved page access, rendered server-side to avoid an identity flash."""
    u = session.get("user") or {}
    name = u.get("name", "")
    initials = "".join(w[0] for w in name.split()).upper()[:2] if name else "?"
    # Prefer the per-user resolved set stored at login time (honors any
    # Settings > Users > Access override); fall back to role defaults for
    # sessions established before that field existed.
    session_allowed = u.get("allowed_pages")
    allowed = set(session_allowed) if session_allowed else ROLE_PERMISSIONS.get(u.get("role"), set())
    return {
        "current_user": u,
        "current_user_initials": initials,
        "allowed_pages": allowed,
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
        low_stock = scalar(
            "SELECT COUNT(*) FROM materials WHERE current_stock < reorder_level;")

        # Transactions in the most recent month that has any records.
        monthly_txns = scalar("""
            SELECT COUNT(*) FROM transactions
            WHERE date_trunc('month', txn_date) = (
                SELECT date_trunc('month', MAX(txn_date)) FROM transactions
            );
        """)

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
        } for r in recent]

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

        return jsonify({"ok": True, "data": {
            "kpi": {
                "activeProjects": int(active_projects),
                "monthlyTxns": int(monthly_txns),
                "totalItems": int(total_items),
                "lowStock": int(low_stock),
            },
            "recent": recent_list,
            "alert": alert,
            "usage": usage_list,
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


def _apply_movement(material_code, quantity, kind, remarks, project_id=None, recorded_by=None, is_damaged=False, back_order_by=None):
    """
    Record a stock movement and adjust the balance.

    kind = 'RECEIPT'  (stock in from supplier, increases balance),
           'ISSUANCE' (stock out to project/customer, decreases balance), or
           'RETURN'   (back-order: material returned by a customer. Logged
                       in the Back Orders table/report and the Stock
                       Movement Summary, but does NOT change
                       materials.current_stock - a back order is tracked
                       separately from on-hand stock, not folded into it,
                       so the material's "pcs on hand" figure everywhere
                       else in the app (Inventory, Dashboard's Low Stock
                       list, etc.) only ever reflects actual Stock In /
                       Stock Out, never a return).

    For issuances this ENFORCES the non-negative-stock rule required by
    Objective 1.1 and test Table 2 - an over-issuance is rejected outright,
    not silently clamped to zero.

    recorded_by: display name of the logged-in user performing this action,
    stored alongside the movement so the Stock In / Stock Out / Back Orders
    tables can show who did it - independent of `remarks`, which describes
    the movement itself (a delivery note, a project reference), not the
    person.

    is_damaged: dormant - RETURN never touches current_stock any more
    (see above), so "damaged vs good" no longer changes the balance
    math either way. The column and parameter are kept only so historical
    rows and the Back Orders report/badge still mean what they always
    meant, not because anything can set it True from the UI any more.

    back_order_by: only meaningful when kind='RETURN'. The customer or
    project that returned the material - who initiated the back order -
    stored as its own column so the Back Orders table/report can show it
    separately from `recorded_by` (the staff member who typed it in) and
    from `remarks` (the free-text reason for the return).
    """
    rows = execute_query(DB_CONFIG,
        "SELECT material_id, material_name, unit, current_stock FROM materials WHERE material_code=%s;",
        (material_code,), fetch=True)
    if not rows:
        raise ValueError("That material was not found.")
    m = rows[0]
    balance = float(m["current_stock"])
    quantity = float(quantity)
    is_damaged = bool(is_damaged) and kind == "RETURN"

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    if kind == "ISSUANCE" and quantity > balance:
        raise ValueError(
            f"Cannot issue {quantity:g} {m['unit']} — only {balance:g} in stock.")

    # RECEIPT adds stock, ISSUANCE subtracts - a RETURN (back order) is
    # logged but deliberately leaves current_stock untouched either way;
    # see the kind/is_damaged docstring notes above for why.
    if kind == "ISSUANCE":
        new_balance = balance - quantity
    elif kind == "RETURN":
        new_balance = balance
    else:
        new_balance = balance + quantity

    back_order_by = (back_order_by or None) if kind == "RETURN" else None

    execute_query(DB_CONFIG, """
        INSERT INTO stock_movements
            (material_id, movement_type, quantity, movement_date, project_id, remarks, recorded_by, is_damaged, back_order_by)
        VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, %s, %s, %s);
    """, (m["material_id"], kind, quantity, project_id, remarks, recorded_by, is_damaged, back_order_by))

    execute_query(DB_CONFIG,
        "UPDATE materials SET current_stock=%s WHERE material_id=%s;",
        (new_balance, m["material_id"]))

    return m["material_name"], new_balance


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
    project. Logged with movement_type = 'RETURN' so the Back Orders
    table/report and the Stock Movement Summary can show it, but it does
    NOT change the material's on-hand current_stock - a back order is
    tracked as its own figure, separate from actual Stock In/Stock Out,
    so it never inflates the "pcs on hand" shown on Inventory or the
    Dashboard's Low Stock list.
    """
    d = request.get_json(silent=True) or {}
    try:
        remarks = d.get("remarks") or ""
        customer = (d.get("customer") or "").strip()
        name, bal = _apply_movement(d.get("itemId"), d.get("qty"), "RETURN",
                                    remarks,
                                    recorded_by=session["user"]["name"],
                                    back_order_by=customer or None)
        log_audit(DB_CONFIG, "STOCK_RETURN",
                  f"{d.get('qty')} of {name} logged as a back order (on-hand stock unchanged, still {bal:g})."
                  + (f" Back-ordered by {customer}." if customer else ""),
                  session["user"]["username"])
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@app.route("/api/inventory/summary")
@permission_required("inventory")
def api_inventory_summary():
    """
    Per-material aggregated totals across the entire stock_movements
    history: Total In (RECEIPT), Total Out (ISSUANCE), and Back Orders
    (RETURN — material that came back from a customer or project).

    Back Orders is informational only - it does NOT feed into Net Stock.
    A back order is logged (so the Back Orders table/report can show it)
    but deliberately never changes materials.current_stock (see
    _apply_movement in app.py), so Net Stock = In - Out, which for any
    material with no manual adjustments equals the current on-hand
    quantity in materials.current_stock — surfacing the same number two
    ways is a quick reconciliation check for the person managing
    inventory. "damagedReturn" is a leftover field from a removed UI
    control (see _apply_movement's is_damaged docstring note); it no
    longer affects anything and is always 0 for any return logged since
    that control was removed.
    """
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT m.material_code, m.material_name, m.category, m.unit,
                   m.current_stock,
                   COALESCE(SUM(CASE WHEN sm.movement_type = 'RECEIPT'  THEN sm.quantity ELSE 0 END), 0) AS total_in,
                   COALESCE(SUM(CASE WHEN sm.movement_type = 'ISSUANCE' THEN sm.quantity ELSE 0 END), 0) AS total_out,
                   COALESCE(SUM(CASE WHEN sm.movement_type = 'RETURN' AND NOT sm.is_damaged THEN sm.quantity ELSE 0 END), 0) AS total_return,
                   COALESCE(SUM(CASE WHEN sm.movement_type = 'RETURN' AND sm.is_damaged     THEN sm.quantity ELSE 0 END), 0) AS total_damaged
              FROM materials m
              LEFT JOIN stock_movements sm ON sm.material_id = m.material_id
             GROUP BY m.material_id, m.material_code, m.material_name,
                      m.category, m.unit, m.current_stock
             ORDER BY m.material_code;
        """, fetch=True)
        data = [{
            "id":            r["material_code"],
            "name":          r["material_name"],
            "cat":           r["category"] or "Uncategorized",
            "unit":          r["unit"],
            "totalIn":       float(r["total_in"]),
            "totalOut":      float(r["total_out"]),
            "backOrder":     float(r["total_return"]),
            "damagedReturn": float(r["total_damaged"]),
            "netStock":      float(r["total_in"]) - float(r["total_out"]),
            "onHand":        float(r["current_stock"]),
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
        # Remove dependent stock movements first (FK safety).
        execute_query(DB_CONFIG, """
            DELETE FROM stock_movements
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
    Full stock movement history (both RECEIPT and ISSUANCE), joined to
    each material's current code/name/unit, most recent first. The
    Inventory page splits this by `type` into its Stock In and Stock Out
    tables. `id` is the material's code, matching the same value used
    everywhere else on the page - so the existing Edit/Delete wiring
    (inventoryStore.find(id) / inventoryStore.remove(id)) works
    unchanged when those actions live on a movement row instead of a
    material-snapshot row.
    """
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT sm.movement_id, m.material_code, m.material_name, m.unit,
                   m.category, sm.movement_type, sm.quantity, sm.movement_date,
                   sm.remarks, sm.recorded_by, sm.is_damaged, sm.back_order_by
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
            "type":       r["movement_type"],   # 'RECEIPT', 'ISSUANCE' or 'RETURN'
            "qty":        float(r["quantity"]),
            "date":       str(r["movement_date"]),
            "remarks":    r["remarks"] or "",
            "recordedBy": r["recorded_by"] or "\u2014",
            # Only meaningful for type='RETURN' - a damaged return was
            # logged but did NOT add back to current_stock (see
            # _apply_movement in app.py). Always False for RECEIPT/ISSUANCE.
            "isDamaged":  bool(r["is_damaged"]),
            # Only meaningful for type='RETURN' - who returned the material
            # (customer/project), distinct from recordedBy (the staff user
            # who entered it).
            "backOrderBy": r["back_order_by"] or "",
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
            row = execute_query(DB_CONFIG, """
                SELECT COALESCE(MAX(CAST(SUBSTRING(supplier_code FROM 5) AS INTEGER)), 400) + 1 AS n
                FROM suppliers WHERE supplier_code LIKE 'SUP-%';
            """, fetch=True)
            code = f"SUP-{row[0]['n']}"
            execute_query(DB_CONFIG, """
                INSERT INTO suppliers
                    (supplier_code, name, contact_person, phone, email, address,
                     category, terms, status, remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, (code,) + fields)
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
                   c.customer_code
            FROM projects p
            LEFT JOIN customers c ON c.customer_id = p.customer_id
            WHERE p.project_code IS NOT NULL
            ORDER BY p.start_date DESC;
        """, fetch=True)
        # Map DB status to the frontend's wording (Ongoing -> In Progress).
        status_map = {"Ongoing": "In Progress", "Completed": "Completed"}
        data = [{
            "id": r["project_code"], "name": r["project_name"],
            "custId": r["customer_code"] or "", "staffId": r["staff"] or "",
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
            _order = ["dashboard", "inventory", "customers", "projects",
                      "transactions", "forecasting", "reports", "settings",
                      "profile"]
            new_value = ",".join(p for p in _order if p in cleaned)
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

        _order = ["dashboard", "inventory", "customers", "projects",
                  "transactions", "forecasting", "reports", "settings", "profile"]
        new_value = ",".join(p for p in _order if p in current)

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
        return jsonify({"ok": True, "data": run_forecast(DB_CONFIG, overrides=overrides)})
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
