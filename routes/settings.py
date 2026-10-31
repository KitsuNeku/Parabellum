import re

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session, current_app

from config import DB_CONFIG
from db import execute_query, log_audit, get_company_settings, get_security_settings, SESSION_TIMEOUTS
import mailer
from backup import generate_sql_backup, restore_sql_backup
from auth import login_required, permission_required, _session_user

bp = Blueprint("settings", __name__)


@bp.route("/api/settings/backup")
@permission_required("settings")
def api_settings_backup():
    sql_text = generate_sql_backup(DB_CONFIG)
    filename = f"parabellum_backup_{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%S')}.sql"
    log_audit(DB_CONFIG, "BACKUP_CREATED", f"Generated backup file {filename}.",
              session["user"]["username"])
    return jsonify({"ok": True, "filename": filename, "sql": sql_text})


@bp.route("/api/settings/restore", methods=["POST"])
@permission_required("settings")
def api_settings_restore():
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
        current_app.logger.exception("Database error")
        return jsonify({"ok": False, "error": "Restore failed partway through, so the database was left unchanged. Please check that this is a genuine Parabellum backup file and try again, or contact your administrator."}), 500

    signed_in_user_id = session["user"]["user_id"]
    signed_in_username = session["user"]["username"]
    try:
        log_audit(DB_CONFIG, "DATABASE_RESTORED", f"Restored database from {filename}.",
                  signed_in_username)
    except Exception:
        pass

    stayed_signed_in = False
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT user_id, username, full_name, role, email, is_active, custom_permissions,
                   totp_enabled, must_change_password
            FROM users WHERE user_id = %s AND username = %s;
        """, (signed_in_user_id, signed_in_username), fetch=True)
        u = rows[0] if rows else None
        if u and u["is_active"]:
            session["user"] = _session_user(DB_CONFIG, u)
            stayed_signed_in = True
    except Exception:
        current_app.logger.exception("Could not re-check the signed-in account after restore")

    if not stayed_signed_in:
        session.clear()
    return jsonify({"ok": True, "stayed_signed_in": stayed_signed_in})


@bp.route("/api/audit-logs")
@permission_required("settings")
def api_audit_logs():
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


COMPANY_FIELDS = {"company_name": 150, "tin": 30, "email": 150, "phone": 40, "address": 250}
CURRENCIES = {"PHP", "USD"}


@bp.route("/api/settings/company")
@login_required
def api_company_get():
    return jsonify({"ok": True, "data": get_company_settings(DB_CONFIG)})


@bp.route("/api/settings/company", methods=["POST"])
@permission_required("settings")
def api_company_save():
    d = request.get_json(silent=True) or {}
    values = {}
    for field, limit in COMPANY_FIELDS.items():
        v = (d.get(field) or "").strip()
        if len(v) > limit:
            return jsonify({"ok": False, "error": f"{field.replace('_', ' ').title()} is too long."}), 400
        values[field] = v
    if not values["company_name"]:
        return jsonify({"ok": False, "error": "Company name is required."}), 400
    if values["email"] and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", values["email"]):
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400
    currency = (d.get("currency") or "PHP").strip().upper()
    if currency not in CURRENCIES:
        return jsonify({"ok": False, "error": "Unsupported currency."}), 400
    try:
        vat = float(d.get("vat_rate"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "VAT rate must be a number."}), 400
    if not 0 <= vat <= 100:
        return jsonify({"ok": False, "error": "VAT rate must be between 0 and 100."}), 400

    execute_query(DB_CONFIG, """
        INSERT INTO company_settings (id, company_name, tin, email, phone, address, currency,
                                      vat_rate, updated_at, updated_by)
        VALUES (1, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
        ON CONFLICT (id) DO UPDATE SET
            company_name = EXCLUDED.company_name, tin = EXCLUDED.tin, email = EXCLUDED.email,
            phone = EXCLUDED.phone, address = EXCLUDED.address, currency = EXCLUDED.currency,
            vat_rate = EXCLUDED.vat_rate, updated_at = CURRENT_TIMESTAMP,
            updated_by = EXCLUDED.updated_by;
    """, (values["company_name"], values["tin"], values["email"], values["phone"],
          values["address"], currency, vat, session["user"]["username"]))
    log_audit(DB_CONFIG, "COMPANY_UPDATED", "Updated company information.",
              session["user"]["username"])
    return jsonify({"ok": True, "data": get_company_settings(DB_CONFIG)})


@bp.route("/api/settings/security")
@permission_required("settings")
def api_security_get():
    data = get_security_settings(DB_CONFIG, fresh=True)
    data["emailConfigured"] = mailer.is_configured()
    data["timeouts"] = list(SESSION_TIMEOUTS)
    return jsonify({"ok": True, "data": data})


@bp.route("/api/settings/security", methods=["POST"])
@permission_required("settings")
def api_security_save():
    d = request.get_json(silent=True) or {}
    current = get_security_settings(DB_CONFIG, fresh=True)
    timeout = d.get("session_timeout_min", current["session_timeout_min"])
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid session timeout."}), 400
    if timeout not in SESSION_TIMEOUTS:
        return jsonify({"ok": False, "error": "Invalid session timeout."}), 400
    require_2fa = bool(d.get("require_2fa_admins", current["require_2fa_admins"]))
    alerts = bool(d.get("login_alerts", current["login_alerts"]))
    if alerts and not mailer.is_configured():
        return jsonify({"ok": False, "error": "Set up the email server first (SMTP settings) to use login alerts."}), 400
    if require_2fa and not session["user"].get("two_factor"):
        return jsonify({"ok": False, "error": "Turn on two-factor authentication for your own account first (My Profile), so you don't lock yourself out."}), 400
    execute_query(DB_CONFIG, """
        UPDATE company_settings SET session_timeout_min = %s, require_2fa_admins = %s, login_alerts = %s,
               updated_at = CURRENT_TIMESTAMP, updated_by = %s
        WHERE id = 1;
    """, (timeout, require_2fa, alerts, session["user"]["username"]))
    data = get_security_settings(DB_CONFIG, fresh=True)
    log_audit(DB_CONFIG, "SECURITY_UPDATED",
              f"Session timeout {timeout} min, admin 2FA {'required' if require_2fa else 'optional'}, "
              f"login alerts {'on' if alerts else 'off'}.", session["user"]["username"])
    data["emailConfigured"] = mailer.is_configured()
    data["timeouts"] = list(SESSION_TIMEOUTS)
    return jsonify({"ok": True, "data": data})
