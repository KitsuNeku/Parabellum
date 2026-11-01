from flask import Blueprint, jsonify, request, session
import psycopg2.errors

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import permission_required
from routes.inventory import _material_row

bp = Blueprint("suppliers", __name__)


@bp.route("/api/suppliers")
@permission_required("suppliers")
def api_suppliers():
    rows = execute_query(DB_CONFIG, """
        SELECT supplier_id, supplier_code, name, contact_person, phone, email, address,
               category, terms, status, remarks, created_at
        FROM suppliers ORDER BY name;
    """, fetch=True)
    mats = execute_query(DB_CONFIG, """
        SELECT s.supplier_id, m.material_code, m.material_name, m.unit, m.unit_cost,
               m.current_stock, m.reorder_level, m.category, m.supplier, m.location,
               m.added_date, 0 AS back_ordered
        FROM materials m
        JOIN suppliers s ON s.supplier_id = m.supplier_id
                         OR (m.supplier_id IS NULL AND LOWER(TRIM(m.supplier)) = LOWER(TRIM(s.name)))
        ORDER BY m.material_name;
    """, fetch=True)
    by_supplier = {}
    for m in mats:
        by_supplier.setdefault(m["supplier_id"], []).append(_material_row(m))
    data = [{
        "id": r["supplier_code"], "name": r["name"],
        "contact": r["contact_person"] or "", "phone": r["phone"] or "",
        "email": r["email"] or "", "addr": r["address"] or "",
        "category": r["category"] or "", "terms": r["terms"] or "",
        "status": r["status"], "remarks": r["remarks"] or "",
        "dateAdded": str(r["created_at"].date()) if r["created_at"] else "",
        "materials": by_supplier.get(r["supplier_id"], []),
    } for r in rows]
    return jsonify({"ok": True, "data": data})


@bp.route("/api/suppliers/save", methods=["POST"])
@permission_required("suppliers")
def api_suppliers_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Company name is required."}), 400
    edit_id = d.get("edit_id")

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
        execute_query(DB_CONFIG, """
            UPDATE materials SET supplier = %s
            WHERE supplier_id = (SELECT supplier_id FROM suppliers WHERE supplier_code = %s);
        """, (name, edit_id))
        log_audit(DB_CONFIG, "SUPPLIER_UPDATED", f"Edited {edit_id} ({name}).",
                  session["user"]["username"])
    else:
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


@bp.route("/api/suppliers/delete", methods=["POST"])
@permission_required("suppliers")
def api_suppliers_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    execute_query(DB_CONFIG, "DELETE FROM suppliers WHERE supplier_code=%s;", (code,))
    log_audit(DB_CONFIG, "SUPPLIER_DELETED", f"Deleted {code}.",
              session["user"]["username"])
    return jsonify({"ok": True})
