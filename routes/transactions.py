from flask import Blueprint, jsonify, request, session

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import permission_required
from routes.inventory import _stock_tx, _weather_for_today

bp = Blueprint("transactions", __name__)


@bp.route("/api/transactions")
@permission_required("transactions")
def api_transactions():
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
        "cust": r["customer_name"] or "—",
        "proj": r["project_code"] or "—",
        "material": r["material_name"] or "—",
        "qty": float(r["quantity"] or 0),
        "price": float(r["unit_price"] or 0),
        "pay": r["payment_status"] or "Pending",
        "method": r["payment_method"] or "",
        "date": str(r["txn_date"]) if r["txn_date"] else "",
    } for r in rows]
    return jsonify({"ok": True, "data": data})


@bp.route("/api/transactions/save", methods=["POST"])
@permission_required("transactions")
def api_transactions_save():
    d = request.get_json(silent=True) or {}
    material_name = (d.get("material") or "").strip()
    if not material_name:
        return jsonify({"ok": False, "error": "Material is required."}), 400

    qty = float(d.get("qty") or 0)
    price = float(d.get("price") or 0)
    if qty <= 0:
        return jsonify({"ok": False, "error": "Quantity must be greater than zero."}), 400
    if price < 0:
        return jsonify({"ok": False, "error": "Unit price cannot be negative."}), 400

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

    temp_c, rain_mm, wind_kmh = _weather_for_today()
    with _stock_tx() as cur:
        cur.execute(
            "SELECT material_id, current_stock, unit FROM materials WHERE material_name=%s FOR UPDATE;",
            (material_name,))
        m = cur.fetchone()
        mat = bool(m)
        if m:
            balance = float(m["current_stock"])
            if qty > balance:
                return jsonify({"ok": False,
                    "error": f"Cannot sell {qty:g} {m['unit']} of {material_name} \u2014 only {balance:g} in stock."}), 400
            cur.execute("""
                INSERT INTO stock_movements
                    (material_id, movement_type, quantity, movement_date, project_id, remarks,
                     weather_temp_c, weather_rainfall_mm, weather_wind_kmh)
                VALUES (%s, 'ISSUANCE', %s, CURRENT_DATE, %s, %s, %s, %s, %s);
            """, (m["material_id"], qty, proj_id, "Sold via transaction", temp_c, rain_mm, wind_kmh))
            cur.execute("UPDATE materials SET current_stock = current_stock - %s WHERE material_id=%s;",
                        (qty, m["material_id"]))

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
