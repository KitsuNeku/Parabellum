from functools import wraps
from datetime import datetime, timedelta, timezone
import secrets

from flask import session, jsonify, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash

from db import execute_query, log_audit, get_security_settings
import mailer

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

ABSOLUTE_SESSION_HOURS = 12


def _session_expired():
    login_at = session.get("login_at")
    if not login_at:
        return True
    try:
        login_dt = datetime.fromisoformat(login_at)
    except (TypeError, ValueError):
        return True
    if login_dt.tzinfo is None:
        login_dt = login_dt.replace(tzinfo=timezone.utc)
    return (_now() - login_dt) > timedelta(hours=ABSOLUTE_SESSION_HOURS)

MIN_PASSWORD_LENGTH = 12


def validate_password_strength(plain_password):
    if not isinstance(plain_password, str):
        raise ValueError("Password must be a string.")
    if len(plain_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    if plain_password.strip() == "":
        raise ValueError("Password cannot be whitespace only.")
    if len(set(plain_password)) < 3:
        raise ValueError("Password is too repetitive (uses fewer than 3 unique characters).")


def hash_password(plain_password):
    validate_password_strength(plain_password)
    return generate_password_hash(plain_password)

ROLE_PERMISSIONS = {
    "System Administrator": {"dashboard", "inventory", "outlook", "suppliers", "customers", "projects",
                              "transactions", "support", "forecasting",
                              "reports", "settings", "profile"},
    "Inventory Personnel":  {"dashboard", "inventory", "outlook", "suppliers", "profile"},
    "Operations Personnel": {"dashboard", "projects", "transactions", "support", "profile"},
    "Management/Owner":     {"dashboard", "outlook", "projects", "transactions", "support",
                              "forecasting", "reports", "profile"},
}

ROLE_NAMES = set(ROLE_PERMISSIONS.keys())

ALL_PERMISSIONS = {"dashboard", "inventory", "outlook", "suppliers", "customers", "projects",
                   "transactions", "support", "forecasting", "reports", "settings",
                   "profile"}

_ADMIN_ONLY_PERMISSIONS = {"settings"}


def get_role_permissions(db_config):
    try:
        rows = execute_query(db_config, "SELECT role, permissions FROM role_permissions;", fetch=True)
    except Exception:
        return {role: set(perms) for role, perms in ROLE_PERMISSIONS.items()}
    if not rows:
        return {role: set(perms) for role, perms in ROLE_PERMISSIONS.items()}
    live = {}
    for r in rows:
        parsed = {p.strip() for p in (r["permissions"] or "").split(",") if p.strip()}
        parsed &= ALL_PERMISSIONS
        if r["role"] != "System Administrator":
            parsed -= _ADMIN_ONLY_PERMISSIONS
        live[r["role"]] = parsed
    for role, perms in ROLE_PERMISSIONS.items():
        live.setdefault(role, set(perms))
    return live


def resolve_permissions(role, custom_permissions_csv, role_permissions=None):
    if role_permissions is None:
        role_permissions = ROLE_PERMISSIONS
    role_defaults = role_permissions.get(role, set())
    csv = (custom_permissions_csv or "").strip()
    if not csv:
        return set(role_defaults)
    parsed = {p.strip() for p in csv.split(",") if p.strip()}
    parsed &= ALL_PERMISSIONS
    if role != "System Administrator":
        parsed -= _ADMIN_ONLY_PERMISSIONS
    return parsed


def _now():
    return datetime.now(timezone.utc)


_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def verify_login(db_config, username, plain_password):
    rows = execute_query(
        db_config,
        """SELECT user_id, username, password_hash, full_name, role, email,
                  is_active, failed_attempts, locked_until, custom_permissions,
                  totp_enabled, must_change_password
           FROM users
           WHERE username = %s OR (POSITION('@' IN %s) > 0 AND LOWER(email) = LOWER(%s))
           ORDER BY (username = %s) DESC LIMIT 1;""",
        (username, username, username, username),
        fetch=True,
    )
    user = rows[0] if rows else None

    generic_error = "Invalid username or password."

    if not user:
        check_password_hash(_DUMMY_HASH, plain_password)
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

    execute_query(
        db_config,
        "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE user_id = %s;",
        (user["user_id"],),
    )
    return _session_user(db_config, user), None


def _session_user(db_config, user):
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "name": user["full_name"] or user["username"],
        "role": user["role"],
        "email": user.get("email") or "",
        "two_factor": bool(user.get("totp_enabled")),
        "must_change_password": bool(user.get("must_change_password")),
        "allowed_pages": sorted(resolve_permissions(
            user["role"], user.get("custom_permissions"),
            get_role_permissions(db_config))),
    }


def needs_2fa_setup(db_config, user):
    return (user.get("role") == "System Administrator" and not user.get("two_factor")
            and get_security_settings(db_config)["require_2fa_admins"])


def finalize_login(db_config, user, ip, remember=True):
    session.clear()
    session["user"] = user
    session["login_at"] = _now().isoformat()
    session["checked_at"] = _now().timestamp()
    session["last_seen"] = _now().timestamp()
    session.permanent = bool(remember)
    log_audit(db_config, "LOGIN_SUCCESS", f"'{user['username']}' signed in from {ip}.", user["username"])
    rows = execute_query(db_config, "SELECT last_login_ip FROM users WHERE user_id = %s;",
                         (user["user_id"],), fetch=True)
    previous_ip = rows[0]["last_login_ip"] if rows else None
    execute_query(db_config,
                  "UPDATE users SET last_login_ip = %s, last_login_at = CURRENT_TIMESTAMP WHERE user_id = %s;",
                  (ip, user["user_id"]))
    if (previous_ip and previous_ip != ip and user.get("email")
            and get_security_settings(db_config)["login_alerts"]):
        mailer.send_async(
            user["email"], "New sign-in to Parabellum ISOS",
            f"Hi {user['name']},\n\nYour account ({user['username']}) was just signed in from a new "
            f"location (IP {ip}) on {_now().astimezone().strftime('%B %d, %Y %I:%M %p')}.\n\n"
            "If this was you, no action is needed. If not, change your password right away and "
            "contact your administrator.\n\nParabellum ISOS")
        log_audit(db_config, "LOGIN_ALERT_SENT", f"New-IP sign-in alert for '{user['username']}'.", user["username"])
    return {
        "mustChangePassword": user["must_change_password"],
        "setup2fa": needs_2fa_setup(db_config, user),
    }


REVALIDATE_SECONDS = 60
GATE_ALLOWED_PREFIXES = ("/profile", "/api/profile", "/api/me", "/api/logout", "/api/notifications",
                         "/api/chat")


def _refresh_session_user(db_config):
    checked = session.get("checked_at", 0)
    if _now().timestamp() - checked < REVALIDATE_SECONDS:
        return True
    rows = execute_query(db_config, """
        SELECT user_id, username, full_name, role, email, is_active, custom_permissions,
               totp_enabled, must_change_password
        FROM users WHERE user_id = %s;
    """, (session["user"].get("user_id"),), fetch=True)
    if not rows or not rows[0]["is_active"] or rows[0]["username"] != session["user"].get("username"):
        return False
    session["user"] = _session_user(db_config, rows[0])
    session["checked_at"] = _now().timestamp()
    return True


def _gate():
    from config import DB_CONFIG
    idle_limit = get_security_settings(DB_CONFIG)["session_timeout_min"] * 60
    idle = _now().timestamp() - session.get("last_seen", _now().timestamp())
    if "user" not in session or _session_expired() or idle > idle_limit \
            or not _refresh_session_user(DB_CONFIG):
        if "user" in session:
            session.clear()
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Not signed in."}), 401
        return redirect(url_for("login"))
    session["last_seen"] = _now().timestamp()
    user = session["user"]
    if (user.get("must_change_password") or needs_2fa_setup(DB_CONFIG, user)) \
            and not request.path.startswith(GATE_ALLOWED_PREFIXES):
        if request.path.startswith("/api/"):
            msg = ("Please change your temporary password first." if user.get("must_change_password")
                   else "Please set up two-factor authentication first.")
            return jsonify({"ok": False, "error": msg}), 403
        return redirect("/profile")
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        blocked = _gate()
        if blocked is not None:
            return blocked
        return view(*args, **kwargs)
    return wrapped


def permission_required(key):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            blocked = _gate()
            if blocked is not None:
                return blocked
            role = session["user"]["role"]
            session_allowed = session["user"].get("allowed_pages")
            allowed = set(session_allowed) if session_allowed else ROLE_PERMISSIONS.get(role, set())
            if key not in allowed:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "error": "Your role does not have access to this."}), 403
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorator


PAGES = ["dashboard", "inventory", "outlook", "suppliers", "customers", "projects", "transactions", "support",
         "forecasting", "reports", "settings", "profile"]


def allowed_pages():
    u = session.get("user") or {}
    session_allowed = u.get("allowed_pages")
    return set(session_allowed) if session_allowed else ROLE_PERMISSIONS.get(u.get("role"), set())
