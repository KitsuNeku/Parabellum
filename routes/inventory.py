from contextlib import contextmanager

from flask import Blueprint, jsonify, request, session
from psycopg2.extras import RealDictCursor

import weather_api
from config import DB_CONFIG
from db import connect_db, execute_query, log_audit
from auth import permission_required

bp = Blueprint("inventory", __name__)


def _inv_status(qty, reorder):
    qty = float(qty)
    reorder = float(reorder)
    if qty <= 0:
        return "Out of Stock"
    if qty <= reorder:
        return "Low Stock"
    return "In Stock"


def _material_row(r):
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
        "backOrdered": float(r.get("back_ordered") or 0),
    }


@bp.route("/api/inventory")
@permission_required("inventory")
def api_inventory():
    rows = execute_query(DB_CONFIG, """
        SELECT material_id, material_code, material_name, unit, unit_cost,
               current_stock, reorder_level, category, supplier, location, added_date,
               COALESCE((SELECT SUM(bo.quantity) FROM back_orders bo
                          WHERE bo.material_id = materials.material_id), 0) AS back_ordered
        FROM materials ORDER BY material_name;
    """, fetch=True)
    return jsonify({"ok": True, "data": [_material_row(r) for r in rows]})


def _supplier_id_for(name):
    name = (name or "").strip()
    if not name:
        return None
    rows = execute_query(DB_CONFIG,
        "SELECT supplier_id FROM suppliers WHERE LOWER(TRIM(name)) = LOWER(TRIM(%s)) LIMIT 1;",
        (name,), fetch=True)
    return rows[0]["supplier_id"] if rows else None


@bp.route("/api/inventory/save", methods=["POST"])
@permission_required("inventory")
def api_inventory_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Item name is required."}), 400

    try:
        qty = float(d.get("qty") or 0)
        reorder = float(d.get("reorder") or 0)
        price = float(d.get("price") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Quantity, reorder level and price must be numbers."}), 400
    if qty < 0 or reorder < 0 or price < 0:
        return jsonify({"ok": False, "error": "Quantity, reorder level and price cannot be negative."}), 400
    supplier_id = _supplier_id_for(d.get("sup"))
    fields = (name, d.get("cat"), d.get("sup"), d.get("unit") or "pcs",
              price, reorder, d.get("loc"))
    edit_id = d.get("edit_id")

    if not edit_id:
        dup = execute_query(DB_CONFIG,
            "SELECT material_code FROM materials WHERE LOWER(TRIM(material_name)) = LOWER(TRIM(%s));",
            (name,), fetch=True)
        if dup:
            return jsonify({"ok": False, "error":
                f"An item named \"{name}\" already exists ({dup[0]['material_code']}). "
                "Search for it above and pick it from the list instead of typing the name again."}), 400

    if edit_id:
        dup = execute_query(DB_CONFIG,
            "SELECT material_code FROM materials WHERE LOWER(TRIM(material_name)) = LOWER(TRIM(%s)) AND material_code <> %s;",
            (name, edit_id), fetch=True)
        if dup:
            return jsonify({"ok": False, "error":
                f"Another item is already named \"{name}\" ({dup[0]['material_code']})."}), 400
        execute_query(DB_CONFIG, """
            UPDATE materials SET material_name=%s, category=%s, supplier=%s,
                   unit=%s, unit_cost=%s, reorder_level=%s, location=%s, supplier_id=%s
            WHERE material_code=%s;
        """, fields + (supplier_id, edit_id))
        log_audit(DB_CONFIG, "MATERIAL_UPDATED", f"Edited material {edit_id} ({name}).",
                  session["user"]["username"])
    else:
        row = execute_query(DB_CONFIG,
            "SELECT COALESCE(MAX(material_id), 0) + 1 AS n FROM materials;", fetch=True)
        code = f"MAT-{row[0]['n']:04d}"
        new_row = execute_query(DB_CONFIG, """
            INSERT INTO materials
                (material_code, material_name, category, supplier, unit,
                 unit_cost, reorder_level, location, current_stock, added_date, supplier_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE, %s)
            RETURNING material_id;
        """, (code, name, d.get("cat"), d.get("sup"), d.get("unit") or "pcs",
              price, reorder, d.get("loc"), qty, supplier_id), fetch=True)
        log_audit(DB_CONFIG, "MATERIAL_ADDED", f"Added material {code} ({name}).",
                  session["user"]["username"])

        if qty > 0 and new_row:
            temp_c, rain_mm, wind_kmh = _weather_for_today()
            execute_query(DB_CONFIG, """
                INSERT INTO stock_movements
                    (material_id, movement_type, quantity, movement_date, remarks, recorded_by,
                     weather_temp_c, weather_rainfall_mm, weather_wind_kmh)
                VALUES (%s, 'RECEIPT', %s, CURRENT_DATE, %s, %s, %s, %s, %s);
            """, (new_row[0]["material_id"], qty, "Initial stock (new item)",
                  session["user"]["name"], temp_c, rain_mm, wind_kmh))

    return jsonify({"ok": True, "code": edit_id or code})


@contextmanager
def _stock_tx():
    conn = connect_db(DB_CONFIG)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _weather_for_today():
    try:
        day = execute_query(DB_CONFIG, "SELECT CURRENT_DATE AS d;", fetch=True)[0]["d"]
        w = weather_api.fetch_weather_for_day(day)
    except Exception:
        w = None
    if not w:
        return None, None, None
    return w["temp_c"], w["rainfall_mm"], w["wind_kmh"]


def _apply_movement(material_code, quantity, kind, remarks, project_id=None, recorded_by=None):
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a number.")
    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")

    temp_c, rain_mm, wind_kmh = _weather_for_today()

    with _stock_tx() as cur:
        cur.execute(
            "SELECT material_id, material_name, unit, current_stock FROM materials "
            "WHERE material_code=%s FOR UPDATE;", (material_code,))
        m = cur.fetchone()
        if not m:
            raise ValueError("That material was not found.")
        balance = float(m["current_stock"])

        if kind == "ISSUANCE" and quantity > balance:
            raise ValueError(
                f"Cannot issue {quantity:g} {m['unit']} \u2014 only {balance:g} in stock.")

        new_balance = balance - quantity if kind == "ISSUANCE" else balance + quantity

        cur.execute("""
            INSERT INTO stock_movements
                (material_id, movement_type, quantity, movement_date, project_id, remarks, recorded_by,
                 weather_temp_c, weather_rainfall_mm, weather_wind_kmh)
            VALUES (%s, %s, %s, CURRENT_DATE, %s, %s, %s, %s, %s, %s);
        """, (m["material_id"], kind, quantity, project_id, remarks, recorded_by,
              temp_c, rain_mm, wind_kmh))
        cur.execute("UPDATE materials SET current_stock=%s WHERE material_id=%s;",
                    (new_balance, m["material_id"]))

    return m["material_name"], new_balance


def _record_back_order(material_code, quantity, remarks, back_order_by=None, recorded_by=None, stock_out_ref=None):
    rows = execute_query(DB_CONFIG,
        "SELECT material_id, material_name FROM materials WHERE material_code=%s;",
        (material_code,), fetch=True)
    if not rows:
        raise ValueError("That material was not found.")
    m = rows[0]
    try:
        quantity = float(quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a number.")
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
    with _stock_tx() as cur:
        cur.execute("""
            SELECT bo.material_id, bo.quantity, bo.restocked_qty, bo.disposition, m.material_name, m.current_stock, m.unit
              FROM back_orders bo JOIN materials m ON m.material_id = bo.material_id
             WHERE bo.back_order_id = %s
               FOR UPDATE OF bo, m;
        """, (back_order_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError("Back order record not found.")
        if row["disposition"]:
            raise ValueError(f"This back order is already marked {row['disposition']} and can't be changed.")
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
            replaced_qty = None

        if disposition != "Reimbursed":
            reimbursed_amount = None
        elif reimbursed_amount is None or reimbursed_amount <= 0:
            raise ValueError("Amount Reimbursed must be greater than zero.")

        stock_delta = new_restocked_qty - old_restocked_qty
        new_balance = balance + stock_delta
        if new_balance < 0:
            stock_delta = -balance
            new_balance = 0.0

        if stock_delta != 0.0:
            cur.execute("UPDATE materials SET current_stock=%s WHERE material_id=%s;",
                        (new_balance, row["material_id"]))

        cur.execute("""
            UPDATE back_orders
               SET disposition=%s, restocked=%s, restocked_qty=%s,
                   replaced_qty=%s, reimbursed_amount=%s, disposition_notes=%s
             WHERE back_order_id=%s;
        """, (disposition, new_restocked_qty > 0, new_restocked_qty,
              replaced_qty, reimbursed_amount, notes, back_order_id))

    return row["material_name"], new_balance, stock_delta


@bp.route("/api/inventory/stock-in", methods=["POST"])
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


@bp.route("/api/inventory/stock-out", methods=["POST"])
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
        return jsonify({"ok": False, "error": str(e)}), 400


DELIVERY_REASON_MAX_LEN = 500


@bp.route("/api/inventory/stock-out/deliver", methods=["POST"])
@permission_required("inventory")
def api_stock_out_deliver():
    d = request.get_json(silent=True) or {}
    try:
        movement_id = int(d.get("movementId"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid Stock Out record."}), 400
    status = (d.get("status") or "Delivered").strip()
    if status not in ("Delivered", "Failed"):
        return jsonify({"ok": False, "error": "Status must be Delivered or Failed."}), 400
    reason = (d.get("reason") or "").strip()
    if status == "Failed":
        if not reason:
            return jsonify({"ok": False, "error": "Please give a reason the delivery did not push through."}), 400
        if len(reason) > DELIVERY_REASON_MAX_LEN:
            return jsonify({"ok": False, "error": f"Reason can be up to {DELIVERY_REASON_MAX_LEN} characters."}), 400
    else:
        reason = None
    row = _stock_out_row(movement_id)
    if not row:
        return jsonify({"ok": False, "error": "Stock Out record not found."}), 404
    current = delivery_status(row)
    if current != "Pending":
        return jsonify({"ok": False, "error": f"This Stock Out is already {'on standby' if current == 'Standby' else current.lower()}."}), 400
    temp, rain, wind = _weather_for_today()
    column = "delivered_at" if status == "Delivered" else "delivery_failed_at"
    execute_query(DB_CONFIG, f"""
        UPDATE stock_movements
           SET {column} = CURRENT_TIMESTAMP,
               delivery_failure_reason = %s,
               delivery_temp_c = %s, delivery_rainfall_mm = %s, delivery_wind_kmh = %s,
               delivery_attempts = delivery_attempts + 1
         WHERE movement_id = %s AND delivered_at IS NULL AND delivery_failed_at IS NULL
           AND returned_at IS NULL;
    """, (reason, temp, rain, wind, movement_id))
    execute_query(DB_CONFIG, """
        INSERT INTO delivery_attempts (movement_id, outcome, reason, temp_c, rainfall_mm, wind_kmh, recorded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (movement_id, status, reason, temp, rain, wind, session["user"]["name"]))
    if status == "Delivered":
        log_audit(DB_CONFIG, "STOCK_OUT_DELIVERED", f"Stock Out MOV-{movement_id:04d} marked as Delivered.",
                  session["user"]["username"])
    else:
        log_audit(DB_CONFIG, "STOCK_OUT_FAILED",
                  f"Stock Out MOV-{movement_id:04d} failed and is on standby: {reason}",
                  session["user"]["username"])
    return jsonify({"ok": True})


def delivery_status(r):
    if r.get("movement_type") and r["movement_type"] != "ISSUANCE":
        return None
    if r.get("returned_at"):
        return "Returned"
    if r.get("delivered_at"):
        return "Delivered"
    if r.get("delivery_failed_at"):
        return "Standby"
    return "Pending"


def _stock_out_row(movement_id):
    rows = execute_query(DB_CONFIG, """
        SELECT sm.movement_id, sm.movement_type, sm.material_id, sm.quantity, sm.delivered_at,
               sm.delivery_failed_at, sm.returned_at, m.material_name, m.unit
          FROM stock_movements sm JOIN materials m ON m.material_id = sm.material_id
         WHERE sm.movement_id = %s;
    """, (movement_id,), fetch=True)
    if not rows or rows[0]["movement_type"] != "ISSUANCE":
        return None
    return rows[0]


def _movement_id(d):
    try:
        return int(d.get("movementId"))
    except (TypeError, ValueError):
        return None


@bp.route("/api/inventory/stock-out/redeliver", methods=["POST"])
@permission_required("inventory")
def api_stock_out_redeliver():
    movement_id = _movement_id(request.get_json(silent=True) or {})
    row = _stock_out_row(movement_id) if movement_id else None
    if not row:
        return jsonify({"ok": False, "error": "Stock Out record not found."}), 404
    if delivery_status(row) != "Standby":
        return jsonify({"ok": False, "error": "Only failed deliveries on standby can be re-delivered."}), 400
    execute_query(DB_CONFIG, """
        UPDATE stock_movements
           SET delivery_failed_at = NULL, delivery_failure_reason = NULL,
               delivery_temp_c = NULL, delivery_rainfall_mm = NULL, delivery_wind_kmh = NULL
         WHERE movement_id = %s AND delivery_failed_at IS NOT NULL AND returned_at IS NULL;
    """, (movement_id,))
    log_audit(DB_CONFIG, "STOCK_OUT_REDELIVER", f"Stock Out MOV-{movement_id:04d} scheduled for another delivery.",
              session["user"]["username"])
    return jsonify({"ok": True})


@bp.route("/api/inventory/stock-out/return-to-stock", methods=["POST"])
@permission_required("inventory")
def api_stock_out_return_to_stock():
    movement_id = _movement_id(request.get_json(silent=True) or {})
    if not movement_id:
        return jsonify({"ok": False, "error": "Stock Out record not found."}), 404
    with _stock_tx() as cur:
        cur.execute("""
            SELECT sm.movement_type, sm.material_id, sm.quantity, sm.delivered_at, sm.delivery_failed_at,
                   sm.returned_at, m.material_name, m.unit, m.current_stock
              FROM stock_movements sm JOIN materials m ON m.material_id = sm.material_id
             WHERE sm.movement_id = %s
               FOR UPDATE OF sm, m;
        """, (movement_id,))
        row = cur.fetchone()
        if not row or row["movement_type"] != "ISSUANCE":
            return jsonify({"ok": False, "error": "Stock Out record not found."}), 404
        if delivery_status(row) != "Standby":
            return jsonify({"ok": False, "error": "Only failed deliveries on standby can be returned to inventory."}), 400
        new_balance = float(row["current_stock"]) + float(row["quantity"])
        cur.execute("UPDATE materials SET current_stock = %s WHERE material_id = %s;",
                    (new_balance, row["material_id"]))
        cur.execute("""
            UPDATE stock_movements SET returned_at = CURRENT_TIMESTAMP, returned_by = %s
             WHERE movement_id = %s;
        """, (session["user"]["name"], movement_id))
    log_audit(DB_CONFIG, "STOCK_OUT_RETURNED",
              f"Stock Out MOV-{movement_id:04d}: {float(row['quantity']):g} {row['unit']} of "
              f"{row['material_name']} returned to inventory (now {new_balance:g}).",
              session["user"]["username"])
    return jsonify({"ok": True, "newStock": new_balance})


@bp.route("/api/inventory/return", methods=["POST"])
@permission_required("inventory")
def api_inventory_return():
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


@bp.route("/api/inventory/return/disposition", methods=["POST"])
@permission_required("inventory")
def api_inventory_return_disposition():
    d = request.get_json(silent=True) or {}
    back_order_id = d.get("backOrderId") or d.get("movementId")
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
        status = 404 if str(e) == "Back order record not found." else 400
        return jsonify({"ok": False, "error": str(e)}), status


@bp.route("/api/inventory/summary")
@permission_required("inventory")
def api_inventory_summary():
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
                       SUM(CASE WHEN movement_type = 'ISSUANCE' AND returned_at IS NULL THEN quantity ELSE 0 END) AS total_out
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


@bp.route("/api/inventory/delete", methods=["POST"])
@permission_required("inventory")
def api_inventory_delete():
    d = request.get_json(silent=True) or {}
    code = d.get("id")
    rows = execute_query(DB_CONFIG, """
        SELECT m.material_id, m.material_name,
               (SELECT COUNT(*) FROM stock_movements sm
                 WHERE sm.material_id = m.material_id AND sm.movement_type <> 'RECEIPT') AS issued,
               (SELECT COUNT(*) FROM back_orders bo WHERE bo.material_id = m.material_id) AS returns,
               (SELECT COUNT(*) FROM monthly_demand md WHERE md.material_id = m.material_id) AS history
        FROM materials m WHERE m.material_code = %s;
    """, (code,), fetch=True)
    if not rows:
        return jsonify({"ok": False, "error": "That material was not found."}), 404
    m = rows[0]
    if m["issued"] or m["returns"] or m["history"]:
        return jsonify({"ok": False, "error":
            f"{m['material_name']} already has Stock Out, return or forecast history, so it can't be "
            "deleted without losing those records. Edit the item instead."}), 400
    execute_query(DB_CONFIG, "DELETE FROM forecast_results WHERE material_id = %s;", (m["material_id"],))
    execute_query(DB_CONFIG, "DELETE FROM stock_movements WHERE material_id = %s;", (m["material_id"],))
    execute_query(DB_CONFIG, "DELETE FROM materials WHERE material_id = %s;", (m["material_id"],))
    log_audit(DB_CONFIG, "MATERIAL_DELETED", f"Deleted material {code} ({m['material_name']}).",
              session["user"]["username"])
    return jsonify({"ok": True})


@bp.route("/api/inventory/movements")
@permission_required("inventory")
def api_inventory_movements():
    rows = execute_query(DB_CONFIG, """
        SELECT sm.movement_id, m.material_code, m.material_name, m.unit,
               m.category, sm.movement_type, sm.quantity, sm.movement_date,
               sm.remarks, sm.recorded_by,
               sm.weather_temp_c, sm.weather_rainfall_mm, sm.weather_wind_kmh,
               sm.delivered_at, sm.delivery_temp_c, sm.delivery_rainfall_mm,
               sm.delivery_wind_kmh, sm.delivery_failed_at, sm.delivery_failure_reason,
               sm.delivery_attempts, sm.returned_at, sm.returned_by
          FROM stock_movements sm
          JOIN materials m ON m.material_id = sm.material_id
         ORDER BY sm.movement_date DESC, sm.movement_id DESC;
    """, fetch=True)
    _f = lambda v: None if v is None else float(v)
    data = [{
        "id":         r["material_code"],
        "movementId": r["movement_id"],
        "name":       r["material_name"],
        "unit":       r["unit"],
        "cat":        r["category"] or "Uncategorized",
        "type":       r["movement_type"],
        "qty":        float(r["quantity"]),
        "date":       str(r["movement_date"]),
        "remarks":    r["remarks"] or "",
        "recordedBy": r["recorded_by"] or "\u2014",
        "weatherTemp": None if r.get("weather_temp_c") is None else float(r["weather_temp_c"]),
        "weatherRain": None if r.get("weather_rainfall_mm") is None else float(r["weather_rainfall_mm"]),
        "weatherWind": None if r.get("weather_wind_kmh") is None else float(r["weather_wind_kmh"]),
        "deliveredAt":    r["delivered_at"].isoformat() if r.get("delivered_at") else None,
        "deliveryFailedAt": r["delivery_failed_at"].isoformat() if r.get("delivery_failed_at") else None,
        "deliveryFailureReason": r.get("delivery_failure_reason") or None,
        "deliveryTemp":   _f(r.get("delivery_temp_c")),
        "deliveryRain":   _f(r.get("delivery_rainfall_mm")),
        "deliveryWind":   _f(r.get("delivery_wind_kmh")),
        "deliveryAttempts": int(r.get("delivery_attempts") or 0),
        "returnedAt":     r["returned_at"].isoformat() if r.get("returned_at") else None,
        "returnedBy":     r.get("returned_by") or None,
        "deliveryStatus": delivery_status(r),
    } for r in rows]
    return jsonify({"ok": True, "data": data})


@bp.route("/api/inventory/backorders")
@permission_required("inventory")
def api_inventory_backorders():
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
        "disposition":  r["disposition"] or "",
        "restocked":    bool(r["restocked"]),
        "restockedQty": float(r["restocked_qty"] or 0),
        "replacedQty":      float(r["replaced_qty"]) if r["replaced_qty"] is not None else None,
        "reimbursedAmount": float(r["reimbursed_amount"]) if r["reimbursed_amount"] is not None else None,
        "dispositionNotes": r["disposition_notes"] or "",
    } for r in rows]
    return jsonify({"ok": True, "data": data})


@bp.route("/api/inventory/projects-for-stockout")
@permission_required("inventory")
def api_inventory_projects_for_stockout():
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
