from flask import Blueprint, jsonify, request, session, current_app
import requests

import weather_api
import scheduler as retrain_scheduler
from config import DB_CONFIG, AUTO_AGGREGATE_BEFORE_RETRAIN
from mlr_model import aggregate_monthly_demand, get_materials, run_forecast, get_forecast_history, get_latest_run
from auth import permission_required
from security import limiter

bp = Blueprint("forecast", __name__)


@bp.route("/api/materials")
@permission_required("forecasting")
def api_materials():
    mats = get_materials(DB_CONFIG)
    for m in mats:
        for k, v in m.items():
            if hasattr(v, "is_integer") or type(v).__name__ == "Decimal":
                m[k] = float(v)
    return jsonify({"ok": True, "data": mats})


@bp.route("/api/aggregate", methods=["POST"])
@permission_required("forecasting")
def api_aggregate():
    try:
        n = aggregate_monthly_demand(DB_CONFIG)
        return jsonify({"ok": True, "rows": n})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/api/forecast", methods=["POST"])
@permission_required("forecasting")
@limiter.limit("6 per minute")
def api_forecast():
    payload = request.get_json(silent=True) or {}
    overrides = payload.get("overrides") or None

    try:
        weather_api.sync_for_history(DB_CONFIG, username=session["user"]["username"])
    except Exception:
        current_app.logger.warning("Weather sync skipped (weather service unreachable).")
    try:
        aggregate_monthly_demand(DB_CONFIG)
        return jsonify({"ok": True, "data": run_forecast(
            DB_CONFIG, overrides=overrides, username=session["user"]["username"])})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/api/forecast/latest")
@permission_required("forecasting")
def api_forecast_latest():
    return jsonify({"ok": True, "data": get_latest_run(DB_CONFIG)})


@bp.route("/api/forecast_history")
@permission_required("forecasting")
def api_forecast_history():
    rows = get_forecast_history(DB_CONFIG, limit=15)
    return jsonify({"ok": True, "data": rows})


@bp.route("/api/weather/sync", methods=["POST"])
@permission_required("forecasting")
@limiter.limit("6 per hour")
def api_weather_sync():
    payload = request.get_json(silent=True) or {}
    start_date = payload.get("start_date") or weather_api.DEFAULT_START_DATE
    end_date = payload.get("end_date")
    try:
        n = weather_api.sync_weather_to_db(DB_CONFIG, start_date=start_date, end_date=end_date)
        return jsonify({"ok": True, "months_synced": n, "location": weather_api.LOCATION_NAME})
    except requests.exceptions.RequestException as e:
        current_app.logger.exception("Weather API request failed")
        return jsonify({"ok": False, "error": "Could not reach the weather service. Check your internet connection and try again."}), 502
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.route("/api/scheduler/status")
@permission_required("forecasting")
def api_scheduler_status():
    return jsonify({"ok": True, "data": retrain_scheduler.get_status()})


@bp.route("/api/scheduler/retrain_now", methods=["POST"])
@permission_required("forecasting")
@limiter.limit("6 per hour")
def api_scheduler_retrain_now():
    payload = request.get_json(silent=True) or {}
    also_aggregate = bool(payload.get("aggregate_first", False)) and AUTO_AGGREGATE_BEFORE_RETRAIN
    ok, message = retrain_scheduler.run_once(DB_CONFIG, auto_aggregate=also_aggregate)
    status_code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message}), status_code
