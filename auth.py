"""
Parabellum ISOS - Authentication & Access Control
=================================================================
Implements what the capstone documentation requires under
Objective 2.1 ("user authentication and role-based access control")
and the ISO 25010 Security row ("Authentication, role-based access,
password control, audit logs... are evaluated").

What this gives you:
  - Passwords are hashed (never stored or compared in plain text).
  - Sessions are server-side, signed, HttpOnly cookies - the frontend
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
import secrets

from flask import session, jsonify, redirect, url_for, request
from werkzeug.security import generate_password_hash, check_password_hash

from mlr_model import execute_query, log_audit

MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15

# Absolute session lifetime -- separate from the 30-minute IDLE timeout
# (PERMANENT_SESSION_LIFETIME in app.py, refreshed on every request).
# Without this, a session that's used continuously never expires. This
# forces re-authentication at least once every 12 hours no matter how
# active the user is -- a real cap on how long a stolen/left-open
# session cookie stays useful to an attacker.
ABSOLUTE_SESSION_HOURS = 12


def _session_expired():
    """True if the current session has outlived ABSOLUTE_SESSION_HOURS
    since login, regardless of recent activity."""
    login_at = session.get("login_at")
    if not login_at:
        # No timestamp recorded (e.g. a session from before this feature
        # existed) -- treat as expired so it re-authenticates and picks
        # up a fresh timestamp, rather than trusting it indefinitely.
        return True
    try:
        login_dt = datetime.fromisoformat(login_at)
    except (TypeError, ValueError):
        return True
    if login_dt.tzinfo is None:
        login_dt = login_dt.replace(tzinfo=timezone.utc)
    return (_now() - login_dt) > timedelta(hours=ABSOLUTE_SESSION_HOURS)

# Minimum password length. 12 is the NIST recommended floor for
# human-set passwords when combined with lockout + hashing. Longer is
# better but shorter is a real vulnerability (8-char passwords fall to
# offline attack in hours if the hash ever leaks).
MIN_PASSWORD_LENGTH = 12


def validate_password_strength(plain_password):
    """
    Raise ValueError with a user-facing message if the password is too
    weak to accept. Called by both the login/password-change flow AND
    by hash_password itself as a safety net.
    """
    if not isinstance(plain_password, str):
        raise ValueError("Password must be a string.")
    if len(plain_password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
        )
    # Reject the most common structural weaknesses: whitespace-only or a
    # single repeated character. Full password-blacklist checks belong in
    # a dedicated service (e.g. HaveIBeenPwned's k-anonymity API) if you
    # want to add that later.
    if plain_password.strip() == "":
        raise ValueError("Password cannot be whitespace only.")
    if len(set(plain_password)) < 3:
        raise ValueError("Password is too repetitive (uses fewer than 3 unique characters).")


def hash_password(plain_password):
    validate_password_strength(plain_password)
    return generate_password_hash(plain_password)

# Mirrors ROLE_PERMISSIONS in static/js/data.js. The frontend list only
# controls what a user SEES; this dict controls what the backend actually
# ALLOWS. They must be kept in sync - the frontend list without this
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


def _now():
    return datetime.now(timezone.utc)


# A fixed, valid password hash with no corresponding real password. Used
# to burn the same amount of CPU time on an unknown-username login as a
# real password check would take, so response TIMING doesn't leak
# whether a username exists (on top of the error message already being
# identical). Generated once and hardcoded -- it verifies against
# nothing, which is exactly the point.
_DUMMY_HASH = generate_password_hash(secrets.token_urlsafe(32))


def verify_login(db_config, username, plain_password):
    """
    Checks credentials against the users table.
    Returns (user_dict, error_message) - exactly one of the two is set.
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
    # password is wrong - confirming which one it was would tell an
    # attacker which usernames are valid.
    generic_error = "Invalid username or password."

    if not user:
        # Run a real (but pointless) hash comparison anyway, so this
        # branch takes about the same time as the "wrong password"
        # branch below. Without this, an unknown username returns
        # measurably faster than a known one, which is itself an
        # enumeration channel even though the error text is identical.
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

    # Success - clear the failure counter and lock.
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
    """Blocks the route entirely unless a session exists AND hasn't
    exceeded the absolute lifetime. Applies to pages and APIs."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user" not in session or _session_expired():
            session.clear()
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "Not signed in."}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def permission_required(key):
    """
    Enforces ROLE_PERMISSIONS on the SERVER for a given permission key
    (e.g. "forecasting"). This is what actually protects the data - the
    sidebar hiding a link in the browser is only ever a convenience.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user" not in session or _session_expired():
                session.clear()
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
