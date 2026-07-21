"""
Parabellum ISOS — Flask backend
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
from datetime import datetime
import os

from config import DB_CONFIG, SECRET_KEY, DEBUG
from mlr_model import aggregate_monthly_demand, get_materials, run_forecast, execute_query, log_audit
from auth import verify_login, login_required, permission_required, ROLE_PERMISSIONS, hash_password
from security import apply_security


def _user_context():
    """
    Injected into every protected page render so the FIRST HTML the server
    sends already shows the correct signed-in identity and role-filtered
    nav — instead of generic placeholder text that JavaScript corrects a
    moment later. That gap is exactly what caused the "flash of the wrong
    account" you'd see switching between logins.
    """
    u = session.get("user") or {}
    name = u.get("name", "")
    initials = "".join(w[0] for w in name.split()).upper()[:2] if name else "?"
    return {
        "current_user": u,
        "current_user_initials": initials,
        "allowed_pages": ROLE_PERMISSIONS.get(u.get("role"), set()),
    }

app = Flask(__name__)
app.secret_key = SECRET_KEY

# Apply defense-in-depth measures — headers, rate limiting, request size
# caps, session hygiene. See security.py for the full list and honest
# scope caveats (what this covers and what needs infrastructure).
limiter = apply_security(app)

# Session cookie hardening:
#   HTTPONLY — JavaScript cannot read the cookie, so a successful XSS
#              injection still can't steal the session.
#   SAMESITE — the cookie is not sent on cross-site requests, which
#              blocks most CSRF attempts against session-based actions.
#   SECURE   — only sent over HTTPS. Defaults to off for local
#              http://127.0.0.1 development. Set the SESSION_COOKIE_SECURE
#              environment variable to "1" once the app is served over
#              real HTTPS (e.g. behind nginx/Caddy with a certificate, or
#              a host that terminates TLS for you) — the cookie will then
#              refuse to be sent over a plain HTTP connection at all.
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
    PERMANENT_SESSION_LIFETIME=1800,  # auto sign-out after 30 idle minutes
)

PAGES = ["dashboard", "inventory", "customers", "projects", "transactions",
         "commissions", "forecasting", "reports", "settings", "profile"]


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
# matching the sidebar visibility rules — but enforced server-side, so
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
    # granted to all roles, so this is a no-op for them — but customers,
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
    forecast alert, and 6 months of material-usage totals for the chart —
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
            execute_query(DB_CONFIG, """
                INSERT INTO materials
                    (material_code, material_name, category, supplier, unit,
                     unit_cost, reorder_level, location, current_stock, added_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE);
            """, (code, name, d.get("cat"), d.get("sup"), d.get("unit") or "pcs",
                  price, reorder, d.get("loc"), qty))
            log_audit(DB_CONFIG, "MATERIAL_ADDED", f"Added material {code} ({name}).",
                      session["user"]["username"])
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


def _apply_movement(material_code, quantity, kind, remarks, project_id=None):
    """
    Record a stock movement and adjust the balance.

    kind = 'RECEIPT' (stock in, increases) or 'ISSUANCE' (stock out, decreases).
    For issuances this ENFORCES the non-negative-stock rule required by
    Objective 1.1 and test Table 2 — an over-issuance is rejected outright,
    not silently clamped to zero.
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

    new_balance = balance + quantity if kind == "RECEIPT" else balance - quantity

    execute_query(DB_CONFIG, """
        INSERT INTO stock_movements
            (material_id, movement_type, quantity, movement_date, project_id, remarks)
        VALUES (%s, %s, %s, CURRENT_DATE, %s, %s);
    """, (m["material_id"], kind, quantity, project_id, remarks))

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
                                    d.get("remarks") or "Stock received")
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
                                    d.get("ref") or "Material issued")
        log_audit(DB_CONFIG, "STOCK_OUT", f"-{d.get('qty')} from {name} (now {bal:g}).",
                  session["user"]["username"])
        return jsonify({"ok": True})
    except ValueError as e:
        # This is where the negative-stock guard reports back to the user.
        return jsonify({"ok": False, "error": str(e)}), 400
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
        # Don't orphan projects/transactions — just unlink them.
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

    This is Objective 1.3 — "monitor project-related material usage and
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
            SELECT user_id, username, full_name, role, email, department, is_active
            FROM users ORDER BY full_name;
        """, fetch=True)
        data = [{
            "id": f"USR-{r['user_id']:02d}", "username": r["username"],
            "name": r["full_name"] or "", "role": r["role"],
            "email": r["email"] or "", "dept": r["department"] or "",
            "status": "Active" if r["is_active"] else "Suspended",
        } for r in rows]
        return jsonify({"ok": True, "data": data})
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
    if role not in ROLE_PERMISSIONS:
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
        # A duplicate username is the one case worth a specific message —
        # everything else stays generic per the no-internal-detail rule.
        msg = ("That username is already taken." if "UNIQUE" in str(e).upper()
               or "unique" in str(e).lower() else
               "A server error occurred. Please try again or contact your administrator.")
        return jsonify({"ok": False, "error": msg}), 500


@app.route("/api/users/deactivate", methods=["POST"])
@permission_required("settings")
def api_users_deactivate():
    """
    Soft-delete only — never hard-deletes an account, since that would
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


@app.route("/api/profile/avatar", methods=["POST"])
@login_required
def api_profile_avatar():
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file received."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_AVATAR_EXTS:
        return jsonify({"ok": False, "error": "Only PNG, JPG, GIF, or WEBP images are allowed."}), 400

    # Flask already caps the whole request body at MAX_CONTENT_LENGTH (see
    # security.py) — this just gives a clearer, specific error message for
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


# ---------------- Commissions API ----------------
@app.route("/api/commissions")
@permission_required("commissions")
def api_commissions():
    """
    Real per-employee commission data (see reports_export.compute_commissions
    for the formula) plus the four summary stat cards the Commissions page
    shows at the top.
    """
    try:
        rows = compute_commissions(DB_CONFIG)

        total_monthly = sum(e["monthly"] for e in rows)
        completed_total = sum(e["completed"] for e in rows)
        avg_rate = (sum(e["rate"] for e in rows) / len(rows)) if rows else 0
        top = max(rows, key=lambda e: e["commission"], default=None)

        return jsonify({"ok": True, "data": {
            "employees": rows,
            "stats": {
                "total_monthly": total_monthly,
                "completed_total": completed_total,
                "avg_rate": avg_rate,
                "top_earner": {"name": top["name"], "commission": top["commission"]} if top else None,
            },
        }})
    except Exception as e:
        app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


# ---------------- Reports API ----------------
from flask import send_file
from reports_export import REPORT_BUILDERS, generate_pdf, generate_excel, compute_commissions

REPORT_FILE_SLUGS = {
    "inventory": "Inventory_Report", "customer": "Customer_Report",
    "project": "Project_Report", "transaction": "Transaction_Report",
    "commission": "Commission_Report", "forecast": "Forecast_Report",
}


@app.route("/api/reports/<key>/data")
@permission_required("reports")
@limiter.limit("30 per minute")
def api_report_data(key):
    """
    Structured report data for the on-screen preview modal. Same builder
    function that the PDF and Excel routes use — the three formats can
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
    """Material master (D2) — fills the forecasting dropdown from the DB."""
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
    """DFD 3.2 — rebuild monthly_demand (D4) from raw operational records."""
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


if __name__ == "__main__":
    # debug=True must never be used once the app is reachable by anyone
    # other than you — it exposes an interactive code console on errors.
    app.run(host="0.0.0.0", port=5000, debug=DEBUG)
