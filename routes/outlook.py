from datetime import date, timedelta

from flask import Blueprint, jsonify, request, session

import weather_api
from config import DB_CONFIG
from db import execute_query, log_audit
from auth import permission_required, allowed_pages

bp = Blueprint("outlook", __name__)

MIN_SAMPLES = 5


def level_status(qty, critical, reorder):
    if qty <= 0:
        return "Out of Stock"
    if critical > 0 and qty <= critical:
        return "Critical"
    if qty <= reorder:
        return "Low"
    return "OK"


def _rain_bucket(rain):
    if rain is None:
        return None
    if rain < 1:
        return "Dry"
    if rain < 10:
        return "Light rain"
    return "Heavy rain"


FALLBACK_RISK = {"Dry": "Low", "Light rain": "Medium", "Heavy rain": "High"}


def _failure_rates():
    rows = execute_query(DB_CONFIG, """
        SELECT rainfall_mm, outcome FROM delivery_attempts WHERE rainfall_mm IS NOT NULL;
    """, fetch=True)
    stats = {b: {"total": 0, "failed": 0} for b in FALLBACK_RISK}
    for r in rows:
        b = _rain_bucket(float(r["rainfall_mm"]))
        stats[b]["total"] += 1
        stats[b]["failed"] += 1 if r["outcome"] == "Failed" else 0
    out = []
    for b, s in stats.items():
        rate = round(s["failed"] / s["total"] * 100, 1) if s["total"] else None
        out.append({"bucket": b, "deliveries": s["total"], "failed": s["failed"], "failureRate": rate})
    return out


def _risk_for(day, rates):
    w = weather_api.fetch_weather_for_day(day)
    if not w or w.get("rainfall_mm") is None:
        return {"date": str(day), "weather": None, "bucket": None, "risk": None, "basis": None,
                "failureRate": None, "samples": 0}
    bucket = _rain_bucket(w["rainfall_mm"])
    stat = next((r for r in rates if r["bucket"] == bucket), None)
    if stat and stat["deliveries"] >= MIN_SAMPLES:
        rate = stat["failureRate"]
        risk = "Low" if rate < 15 else "Medium" if rate < 35 else "High"
        basis = "history"
    else:
        rate = stat["failureRate"] if stat else None
        risk = FALLBACK_RISK.get(bucket)
        basis = "weather"
    if w.get("wind_kmh") and w["wind_kmh"] >= 50 and risk != "High":
        risk = "High" if risk == "Medium" else "Medium"
    return {"date": str(day), "weather": w, "bucket": bucket, "risk": risk, "basis": basis,
            "failureRate": rate, "samples": stat["deliveries"] if stat else 0}


def delivery_risk():
    rates = _failure_rates()
    today = date.today()
    return {
        "today": _risk_for(today, rates),
        "tomorrow": _risk_for(today + timedelta(days=1), rates),
        "history": rates,
        "minSamples": MIN_SAMPLES,
    }


@bp.route("/api/outlook")
@permission_required("outlook")
def api_outlook():
    mats = execute_query(DB_CONFIG, """
        SELECT m.material_id, m.material_code, m.material_name, m.category, m.unit,
               m.current_stock, m.reorder_level, m.critical_level,
               f.predicted_demand, f.forecast_month,
               COALESCE(d.standby_qty, 0) AS standby_qty, COALESCE(d.standby_count, 0) AS standby_count,
               COALESCE(d.pending_count, 0) AS pending_count
          FROM materials m
          LEFT JOIN forecast_results f
                 ON f.material_id = m.material_id
                AND f.forecast_month = (SELECT MAX(forecast_month) FROM forecast_results)
                AND f.model_name = 'Multiple Linear Regression'
          LEFT JOIN (
                SELECT material_id,
                       SUM(quantity) FILTER (WHERE delivery_failed_at IS NOT NULL AND returned_at IS NULL) AS standby_qty,
                       COUNT(*) FILTER (WHERE delivery_failed_at IS NOT NULL AND returned_at IS NULL) AS standby_count,
                       COUNT(*) FILTER (WHERE delivered_at IS NULL AND delivery_failed_at IS NULL
                                          AND returned_at IS NULL) AS pending_count
                  FROM stock_movements WHERE movement_type = 'ISSUANCE'
                 GROUP BY material_id
          ) d ON d.material_id = m.material_id
         ORDER BY m.material_name;
    """, fetch=True)
    materials = []
    for r in mats:
        qty = float(r["current_stock"])
        critical = float(r["critical_level"] or 0)
        reorder = float(r["reorder_level"] or 0)
        predicted = float(r["predicted_demand"]) if r["predicted_demand"] is not None else None
        materials.append({
            "id": r["material_code"], "name": r["material_name"], "cat": r["category"] or "Uncategorized",
            "unit": r["unit"], "qty": qty, "critical": critical, "reorder": reorder,
            "status": level_status(qty, critical, reorder),
            "predicted": predicted,
            "forecastMonth": r["forecast_month"].strftime("%b %Y") if r["forecast_month"] else None,
            "restock": max(round(predicted - qty, 2), 0.0) if predicted is not None else None,
            "willRunOut": predicted is not None and qty < predicted,
            "standbyQty": float(r["standby_qty"]), "standbyCount": int(r["standby_count"]),
            "pendingCount": int(r["pending_count"]),
        })

    deliveries = execute_query(DB_CONFIG, """
        SELECT sm.movement_id, sm.quantity, sm.movement_date, sm.remarks, sm.delivered_at,
               sm.delivery_failed_at, sm.delivery_failure_reason, sm.returned_at, sm.delivery_attempts,
               sm.delivery_rainfall_mm, sm.delivery_temp_c, sm.delivery_wind_kmh,
               sm.weather_rainfall_mm, sm.weather_temp_c,
               m.material_code, m.material_name, m.unit
          FROM stock_movements sm JOIN materials m ON m.material_id = sm.material_id
         WHERE sm.movement_type = 'ISSUANCE'
           AND (sm.returned_at IS NULL AND sm.delivered_at IS NULL
                OR COALESCE(sm.delivered_at, sm.returned_at) >= CURRENT_DATE - INTERVAL '30 days')
         ORDER BY (sm.delivery_failed_at IS NOT NULL AND sm.returned_at IS NULL) DESC,
                  sm.movement_date DESC, sm.movement_id DESC
         LIMIT 200;
    """, fetch=True)
    _f = lambda v: None if v is None else float(v)
    delivery_rows = []
    for r in deliveries:
        status = ("Returned" if r["returned_at"] else "Delivered" if r["delivered_at"]
                  else "Standby" if r["delivery_failed_at"] else "Pending")
        delivery_rows.append({
            "movementId": r["movement_id"], "id": r["material_code"], "name": r["material_name"],
            "unit": r["unit"], "qty": float(r["quantity"]), "date": str(r["movement_date"]),
            "ref": r["remarks"] or "", "status": status, "attempts": int(r["delivery_attempts"] or 0),
            "reason": r["delivery_failure_reason"] or "",
            "at": (r["delivered_at"] or r["delivery_failed_at"] or r["returned_at"]).isoformat()
                  if (r["delivered_at"] or r["delivery_failed_at"] or r["returned_at"]) else None,
            "rain": _f(r["delivery_rainfall_mm"]) if r["delivery_rainfall_mm"] is not None else _f(r["weather_rainfall_mm"]),
            "temp": _f(r["delivery_temp_c"]) if r["delivery_temp_c"] is not None else _f(r["weather_temp_c"]),
            "wind": _f(r["delivery_wind_kmh"]),
        })

    return jsonify({"ok": True, "data": {
        "materials": materials,
        "deliveries": delivery_rows,
        "summary": {
            "critical": sum(1 for m in materials if m["status"] in ("Critical", "Out of Stock")),
            "low": sum(1 for m in materials if m["status"] == "Low"),
            "willRunOut": sum(1 for m in materials if m["willRunOut"]),
            "standby": sum(m["standbyCount"] for m in materials),
            "pending": sum(m["pendingCount"] for m in materials),
        },
        "canEditCritical": session["user"]["role"] == "System Administrator",
        "canManageDeliveries": "inventory" in allowed_pages(),
    }})


@bp.route("/api/outlook/delivery-risk")
@permission_required("outlook")
def api_delivery_risk():
    return jsonify({"ok": True, "data": delivery_risk()})


@bp.route("/api/outlook/critical", methods=["POST"])
@permission_required("outlook")
def api_set_critical():
    if session["user"]["role"] != "System Administrator":
        return jsonify({"ok": False, "error": "Only a System Administrator can change critical levels."}), 403
    d = request.get_json(silent=True) or {}
    try:
        level = float(d.get("level"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Critical level must be a number."}), 400
    if level < 0:
        return jsonify({"ok": False, "error": "Critical level cannot be negative."}), 400
    rows = execute_query(DB_CONFIG, """
        UPDATE materials SET critical_level = %s WHERE material_code = %s
        RETURNING material_name, unit, current_stock, reorder_level;
    """, (level, d.get("id")), fetch=True)
    if not rows:
        return jsonify({"ok": False, "error": "Material not found."}), 404
    r = rows[0]
    log_audit(DB_CONFIG, "CRITICAL_LEVEL_SET", f"{r['material_name']}: critical level set to {level:g} {r['unit']}.",
              session["user"]["username"])
    return jsonify({"ok": True, "data": {
        "critical": level,
        "status": level_status(float(r["current_stock"]), level, float(r["reorder_level"] or 0)),
    }})
