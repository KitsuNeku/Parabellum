"""
Parabellum ISOS — Authentication & Access Control
=================================================================
Implements what the capstone documentation requires under
Objective 2.1 ("user authentication and role-based access control")
and the ISO 25010 Security row ("Authentication, role-based access,
password control, audit logs... are evaluated").

What this gives you:
  - Passwords are hashed (never stored or compared in plain text).
  - Sessions are server-side, signed, HttpOnly cookies — the frontend
    never holds a password after login.
  - Role checks happen on the SERVER, not just by hiding sidebar
    links in JavaScript. Hiding a link is a UI convenience; it is not
    security, because anyone can call the API directly.
  - Repeated wrong passwords lock the account for a short cooldown,
    which blocks simple brute-force guessing.
  - Every login attempt (success or failure) is written to audit_logs
    (D7), matching Appendix B / your admin test table's requirement
    that audit logs record important activity.
"""

from functools import wraps
from datetime import datetime, timedelta, timezone

from flask import session, jsonify, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash

from mlr_model import execute_query, log_audit

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Mirrors ROLE_PERMISSIONS in static/js/data.js. The frontend list only
# controls what a user SEES; this dict controls what the backend actually
# ALLOWS. They must be kept in sync — the frontend list without this
# backend check would just be a locked door with the key taped to it.
ROLE_PERMISSIONS = {
    "System Administrator": {"dashboard", "inventory", "customers", "projects",
                              "transactions", "commissions", "forecasting",
                              "reports", "settings", "profile"},
    "Inventory Personnel":  {"dashboard", "inventory", "profile"},
    "Operations Personnel": {"dashboard", "projects", "transactions", "profile"},
    "Management/Owner":     {"dashboard", "projects", "transactions",
                              "commissions", "forecasting", "reports", "profile"},
}

# Which permission-key each API endpoint falls under.
API_PERMISSION = {
    "api_materials":  "forecasting",
    "api_aggregate":  "forecasting",
    "api_forecast":   "forecasting",
}


def hash_password(plain_password):
    return generate_password_hash(plain_password)


def _now():
    return datetime.now(timezone.utc)


def verify_login(db_config, username, plain_password):
    """
    Checks credentials against the users table.
    Returns (user_dict, error_message) — exactly one of the two is set.
    """
    rows = execute_query(
        db_config,
        """SELECT user_id, username, password_hash, full_name, role,
                  is_active, failed_attempts, locked_until
           FROM users WHERE username = %s;""",
        (username,),
        fetch=True,
    )
    user = rows[0] if rows else None

    # Same generic message whether the username doesn't exist or the
    # password is wrong — confirming which one it was would tell an
    # attacker which usernames are valid.
    generic_error = "Invalid username or password."

    if not user:
        log_audit(db_config, "LOGIN_FAILED", f"Unknown username '{username}'.")
        return None, generic_error

    if not user["is_active"]:
        log_audit(db_config, "LOGIN_BLOCKED", f"'{username}' account is disabled.", username)
        return None, "This account has been disabled. Contact your administrator."

    if user["locked_until"]:
        locked_until = user["locked_until"]
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.tzinfo is None:
            locked_until = locked_until.replace(tzinfo=timezone.utc)
        if locked_until > _now():
            minutes_left = max(1, int((locked_until - _now()).total_seconds() // 60) + 1)
            log_audit(db_config, "LOGIN_LOCKED", f"'{username}' is locked out.", username)
            return None, f"Too many failed attempts. Try again in {minutes_left} minute(s)."

    if not check_password_hash(user["password_hash"], plain_password):
        attempts = (user["failed_attempts"] or 0) + 1
        if attempts >= MAX_FAILED_ATTEMPTS:
            locked_until = _now() + timedelta(minutes=LOCKOUT_MINUTES)
            execute_query(
                db_config,
                "UPDATE users SET failed_attempts = %s, locked_until = %s WHERE user_id = %s;",
                (attempts, locked_until, user["user_id"]),
            )
            log_audit(db_config, "LOGIN_LOCKOUT_TRIGGERED",
                      f"'{username}' locked for {LOCKOUT_MINUTES} min after {attempts} failed attempts.",
                      username)
            return None, f"Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes."

        execute_query(
            db_config, "UPDATE users SET failed_attempts = %s WHERE user_id = %s;",
            (attempts, user["user_id"]),
        )
        log_audit(db_config, "LOGIN_FAILED", f"Wrong password for '{username}' (attempt {attempts}).", username)
        return None, generic_error

    # Success — clear the failure counter and lock.
    execute_query(
        db_config,
        "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE user_id = %s;",
        (user["user_id"],),
    )
    log_audit(db_config, "LOGIN_SUCCESS", f"'{username}' signed in.", username)

    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "name": user["full_name"] or user["username"],
        "role": user["role"],
    }, None


def login_required(view):
    """Blocks the route entirely unless a session exists. Applies to pages and APIs."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Not signed in."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def permission_required(key):
    """
    Enforces ROLE_PERMISSIONS on the SERVER for a given permission key
    (e.g. "forecasting"). This is what actually protects the data — the
    sidebar hiding a link in the browser is only ever a convenience.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user" not in session:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Not signed in."}), 401
                return redirect(url_for("login"))

            role = session["user"]["role"]
            allowed = ROLE_PERMISSIONS.get(role, set())
            if key not in allowed:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Your role does not have access to this."}), 403
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator
