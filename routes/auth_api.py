import time

from flask import Blueprint, jsonify, request, session

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import verify_login, finalize_login
from security import limiter
import totp

bp = Blueprint("auth_api", __name__)

PENDING_2FA_SECONDS = 300
MAX_2FA_ATTEMPTS = 5


@bp.route("/api/login", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour")
def api_login():
    payload = request.get_json(silent=True) or {}
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not username or not password:
        return jsonify({"ok": False, "error": "Username and password are required."}), 400

    user, error = verify_login(DB_CONFIG, username, password)
    if error:
        return jsonify({"ok": False, "error": error}), 401

    if user["two_factor"]:
        session.clear()
        session["pending_2fa"] = {"user": user, "at": time.time(), "tries": 0,
                                  "remember": payload.get("remember", True) is not False}
        log_audit(DB_CONFIG, "LOGIN_2FA_REQUIRED", f"'{username}' passed password check, waiting for 2FA code.", username)
        return jsonify({"ok": True, "twoFactor": True})

    flags = finalize_login(DB_CONFIG, user, request.remote_addr or "unknown",
                           remember=payload.get("remember", True) is not False)
    return jsonify({"ok": True, "data": session["user"], **flags})


@bp.route("/api/login/2fa", methods=["POST"])
@limiter.limit("10 per minute; 60 per hour")
def api_login_2fa():
    pending = session.get("pending_2fa")
    if not pending or time.time() - pending.get("at", 0) > PENDING_2FA_SECONDS:
        session.clear()
        return jsonify({"ok": False, "error": "Your sign-in timed out. Please enter your password again.", "restart": True}), 401

    user = pending["user"]
    rows = execute_query(DB_CONFIG, """
        SELECT totp_secret, totp_last_step, is_active FROM users WHERE user_id = %s;
    """, (user["user_id"],), fetch=True)
    if not rows or not rows[0]["is_active"]:
        session.clear()
        return jsonify({"ok": False, "error": "This account is not available.", "restart": True}), 401

    code = (request.get_json(silent=True) or {}).get("code")
    step = totp.verify(rows[0]["totp_secret"], code, rows[0]["totp_last_step"])
    if step is None:
        pending["tries"] = pending.get("tries", 0) + 1
        log_audit(DB_CONFIG, "LOGIN_2FA_FAILED", f"Wrong 2FA code for '{user['username']}' (attempt {pending['tries']}).", user["username"])
        if pending["tries"] >= MAX_2FA_ATTEMPTS:
            session.clear()
            return jsonify({"ok": False, "error": "Too many wrong codes. Please sign in again.", "restart": True}), 401
        session["pending_2fa"] = pending
        return jsonify({"ok": False, "error": "That code is not correct. Check your authenticator app and try again."}), 401

    execute_query(DB_CONFIG, "UPDATE users SET totp_last_step = %s WHERE user_id = %s;", (step, user["user_id"]))
    flags = finalize_login(DB_CONFIG, user, request.remote_addr or "unknown",
                           remember=pending.get("remember", True))
    return jsonify({"ok": True, "data": session["user"], **flags})


@bp.route("/api/logout", methods=["POST"])
def api_logout():
    user = session.get("user")
    if user:
        log_audit(DB_CONFIG, "LOGOUT", f"'{user['username']}' signed out.", user["username"])
    session.clear()
    return jsonify({"ok": True})


@bp.route("/api/me")
def api_me():
    if "user" not in session:
        return jsonify({"ok": False, "error": "Not signed in."}), 401
    return jsonify({"ok": True, "data": session["user"]})
