from flask import Blueprint, jsonify, request, session

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import permission_required

bp = Blueprint("projects", __name__)


@bp.route("/api/projects")
@permission_required("projects")
def api_projects():
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
    status_map = {"Ongoing": "In Progress", "Completed": "Completed"}
    data = [{
        "id": r["project_code"], "name": r["project_name"],
        "custId": r["customer_code"] or "", "staffId": r["staff"] or "",
        "cust": r["customer_name"] or "—",
        "staff": r["staff_name"] or r["staff"] or "—",
        "budget": float(r["budget"] or 0),
        "start": str(r["start_date"]) if r["start_date"] else "",
        "due": str(r["end_date"]) if r["end_date"] else "",
        "status": status_map.get(r["status"], r["status"]),
        "priority": r["priority"] or "Medium", "progress": int(r["progress"] or 0),
    } for r in rows]
    return jsonify({"ok": True, "data": data})


@bp.route("/api/employees")
@permission_required("projects")
def api_employees():
    rows = execute_query(DB_CONFIG, """
        SELECT employee_code, name, role, status
        FROM employees ORDER BY employee_code;
    """, fetch=True)
    return jsonify({"ok": True, "data": [{
        "id": r["employee_code"], "name": r["name"],
        "role": r["role"] or "", "status": r["status"] or "Active",
    } for r in rows]})


@bp.route("/api/projects/save", methods=["POST"])
@permission_required("projects")
def api_projects_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Project name is required."}), 400
    cust_id = None
    if d.get("custId"):
        crow = execute_query(DB_CONFIG,
            "SELECT customer_id FROM customers WHERE customer_code=%s;",
            (d.get("custId"),), fetch=True)
        cust_id = crow[0]["customer_id"] if crow else None

    status = "Ongoing" if d.get("status") in (None, "In Progress") else d.get("status")
    try:
        progress = int(float(d.get("progress") or 0))
        budget = float(d.get("budget") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Budget and progress must be numbers."}), 400
    if not d.get("start"):
        return jsonify({"ok": False, "error": "Start date is required."}), 400
    if d.get("due") and d.get("due") < d.get("start"):
        return jsonify({"ok": False, "error": "Due date can't be earlier than the start date."}), 400
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


@bp.route("/api/projects/delete", methods=["POST"])
@permission_required("projects")
def api_projects_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    execute_query(DB_CONFIG, """
        UPDATE transactions SET project_id = NULL
        WHERE project_id = (SELECT project_id FROM projects WHERE project_code=%s);
    """, (code,))
    execute_query(DB_CONFIG, """
        UPDATE stock_movements SET project_id = NULL
        WHERE project_id = (SELECT project_id FROM projects WHERE project_code=%s);
    """, (code,))
    execute_query(DB_CONFIG, "DELETE FROM projects WHERE project_code=%s;", (code,))
    log_audit(DB_CONFIG, "PROJECT_DELETED", f"Deleted {code}.",
              session["user"]["username"])
    return jsonify({"ok": True})
