from flask import Blueprint, jsonify, request, session

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import permission_required

bp = Blueprint("customers", __name__)


@bp.route("/api/customers")
@permission_required("customers")
def api_customers():
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


@bp.route("/api/customers/save", methods=["POST"])
@permission_required("customers")
def api_customers_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Customer name is required."}), 400
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


@bp.route("/api/customers/delete", methods=["POST"])
@permission_required("customers")
def api_customers_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
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
