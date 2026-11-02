import secrets
import string

import psycopg2.errors

from flask import Blueprint, jsonify, request, session

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import PAGES, permission_required, ROLE_NAMES, ALL_PERMISSIONS, resolve_permissions, get_role_permissions, hash_password

bp = Blueprint("users", __name__)


@bp.route("/api/users")
@permission_required("settings")
def api_users():
    rows = execute_query(DB_CONFIG, """
        SELECT user_id, username, full_name, role, email, department,
               is_active, custom_permissions, totp_enabled, must_change_password,
               locked_until, last_login_at
        FROM users ORDER BY full_name;
    """, fetch=True)
    live_role_perms = get_role_permissions(DB_CONFIG)
    data = []
    for r in rows:
        role_defaults = sorted(live_role_perms.get(r["role"], set()))
        resolved = sorted(resolve_permissions(r["role"], r["custom_permissions"], live_role_perms))
        data.append({
            "id":       f"USR-{r['user_id']:02d}",
            "username": r["username"],
            "name":     r["full_name"] or "",
            "role":     r["role"],
            "email":    r["email"] or "",
            "dept":     r["department"] or "",
            "status":   "Active" if r["is_active"] else "Suspended",
            "customPermissions": r["custom_permissions"] or "",
            "hasOverride":       bool((r["custom_permissions"] or "").strip()),
            "effectivePermissions": resolved,
            "rolePermissions":      role_defaults,
            "twoFactor":   bool(r["totp_enabled"]),
            "mustChangePassword": bool(r["must_change_password"]),
            "lastLogin":   r["last_login_at"].strftime("%b %d, %Y %H:%M") if r["last_login_at"] else "",
        })
    return jsonify({"ok": True, "data": data})


@bp.route("/api/users/permissions", methods=["POST"])
@permission_required("settings")
def api_users_permissions():
    d = request.get_json(silent=True) or {}
    edit_id = d.get("id") or ""
    reset = bool(d.get("reset"))
    perms = d.get("permissions") or []
    if not edit_id.startswith("USR-"):
        return jsonify({"ok": False, "error": "Invalid user id."}), 400
    try:
        user_id = int(edit_id.split("-")[1])
    except (ValueError, IndexError):
        return jsonify({"ok": False, "error": "Invalid user id."}), 400

    rows = execute_query(
        DB_CONFIG,
        "SELECT username, role FROM users WHERE user_id = %s;",
        (user_id,), fetch=True,
    )
    if not rows:
        return jsonify({"ok": False, "error": "User not found."}), 404
    target = rows[0]

    # The admin account's permissions are fixed - cannot be changed from here.
    # Blocks both a toggle-apply and a "reset" (both would alter the admin's
    # effective access).
    if target["username"] == "admin":
        return jsonify({"ok": False,
            "error": "The admin account's permissions cannot be changed."}), 400

    if reset:
        new_value = None
        log_detail = f"Cleared custom permissions for {target['username']} — role defaults now apply."
    else:
        cleaned = {str(p).strip() for p in perms if isinstance(p, str) and p.strip()}
        cleaned &= ALL_PERMISSIONS
        if target["role"] != "System Administrator":
            cleaned.discard("settings")

        me = session["user"]
        if me.get("user_id") == user_id and "settings" not in cleaned:
            return jsonify({
                "ok": False,
                "error": "You can't take away your own Settings access — you would be locked out of this page.",
            }), 400

        new_value = ",".join(p for p in PAGES if p in cleaned)
        log_detail = (f"Set custom permissions for {target['username']} "
                      f"to [{new_value or '(none)'}].")

    execute_query(
        DB_CONFIG,
        "UPDATE users SET custom_permissions = %s WHERE user_id = %s;",
        (new_value, user_id),
    )
    log_audit(DB_CONFIG, "USER_PERMISSIONS_CHANGED", log_detail,
              session["user"]["username"])

    if session["user"].get("user_id") == user_id:
        session["user"]["allowed_pages"] = sorted(
            resolve_permissions(target["role"], new_value, get_role_permissions(DB_CONFIG))
        )
        session.modified = True

    return jsonify({"ok": True})


@bp.route("/api/roles/permissions")
@permission_required("settings")
def api_roles_permissions():
    live = get_role_permissions(DB_CONFIG)
    data = {role: sorted(perms) for role, perms in live.items()}
    return jsonify({"ok": True, "data": data})


@bp.route("/api/roles/permissions/toggle", methods=["POST"])
@permission_required("settings")
def api_roles_permissions_toggle():
    d = request.get_json(silent=True) or {}
    role = d.get("role") or ""
    module = d.get("module") or ""
    enabled = bool(d.get("enabled"))

    if role not in ROLE_NAMES:
        return jsonify({"ok": False, "error": "Invalid role."}), 400
    if module not in ALL_PERMISSIONS:
        return jsonify({"ok": False, "error": "Invalid module."}), 400
    if module == "settings" and enabled and role != "System Administrator":
        return jsonify({"ok": False, "error": "Only System Administrator can have Settings access."}), 400
    if module == "settings" and not enabled and role == "System Administrator":
        return jsonify({"ok": False, "error": "Settings access can't be removed from System Administrator — that would lock everyone out of this page."}), 400

    rows = execute_query(
        DB_CONFIG, "SELECT permissions FROM role_permissions WHERE role = %s;",
        (role,), fetch=True,
    )
    current = {p.strip() for p in (rows[0]["permissions"] or "").split(",") if p.strip()} if rows else set()

    if enabled:
        current.add(module)
    else:
        current.discard(module)

    if not current:
        return jsonify({"ok": False, "error": f"{role} can't be left with zero modules."}), 400

    new_value = ",".join(p for p in PAGES if p in current)

    execute_query(DB_CONFIG, """
        INSERT INTO role_permissions (role, permissions) VALUES (%s, %s)
        ON CONFLICT (role) DO UPDATE SET permissions = EXCLUDED.permissions;
    """, (role, new_value))

    log_audit(DB_CONFIG, "ROLE_PERMISSIONS_CHANGED",
              f"{'Granted' if enabled else 'Revoked'} '{module}' {'to' if enabled else 'from'} "
              f"{role} (now: [{new_value}]).", session["user"]["username"])

    return jsonify({"ok": True, "data": sorted(current)})


@bp.route("/api/users/save", methods=["POST"])
@permission_required("settings")
def api_users_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    username = (d.get("username") or "").strip()
    role = d.get("role") or ""
    email = (d.get("email") or "").strip()
    if not name or not username:
        return jsonify({"ok": False, "error": "Name and username are required."}), 400
    if role not in ROLE_NAMES:
        return jsonify({"ok": False, "error": "Invalid role."}), 400

    edit_id = d.get("edit_id")
    is_active = d.get("status", "Active") != "Suspended"
    password = d.get("password") or ""

    try:
        if edit_id:
            user_id = int(edit_id.split("-")[1])
            current = execute_query(DB_CONFIG,
                "SELECT username, role FROM users WHERE user_id = %s;",
                (user_id,), fetch=True)
            if current and current[0]["username"] == "admin" and role != current[0]["role"]:
                return jsonify({"ok": False,
                    "error": "The admin account's role cannot be changed."}), 400
            if password:
                execute_query(DB_CONFIG, """
                    UPDATE users SET full_name=%s, username=%s, role=%s, email=%s,
                           department=%s, is_active=%s, password_hash=%s
                    WHERE user_id=%s;
                """, (name, username, role, email, d.get("dept"), is_active,
                      hash_password(password), user_id))
            else:
                execute_query(DB_CONFIG, """
                    UPDATE users SET full_name=%s, username=%s, role=%s, email=%s,
                           department=%s, is_active=%s
                    WHERE user_id=%s;
                """, (name, username, role, email, d.get("dept"), is_active, user_id))
            log_audit(DB_CONFIG, "USER_UPDATED", f"Edited {username} ({role}).",
                      session["user"]["username"])
        else:
            if not password:
                return jsonify({"ok": False, "error": "A password is required for new accounts."}), 400
            execute_query(DB_CONFIG, """
                INSERT INTO users (username, password_hash, full_name, role, email, department, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
            """, (username, hash_password(password), name, role, email, d.get("dept"), is_active))
            log_audit(DB_CONFIG, "USER_CREATED", f"Created {username} ({role}).",
                      session["user"]["username"])
        return jsonify({"ok": True})
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except psycopg2.errors.UniqueViolation:
        return jsonify({"ok": False, "error": "That username is already taken."}), 400


@bp.route("/api/users/deactivate", methods=["POST"])
@permission_required("settings")
def api_users_deactivate():
    d = request.get_json(silent=True) or {}
    edit_id = d.get("id") or ""
    try:
        user_id = int(edit_id.split("-")[1])
    except (ValueError, IndexError):
        return jsonify({"ok": False, "error": "Invalid user id."}), 400

    if user_id == session["user"]["user_id"]:
        return jsonify({"ok": False, "error": "You cannot deactivate your own account."}), 400

    execute_query(DB_CONFIG, "UPDATE users SET is_active=FALSE WHERE user_id=%s;", (user_id,))
    log_audit(DB_CONFIG, "USER_DEACTIVATED", f"Deactivated user_id {user_id}.",
              session["user"]["username"])
    return jsonify({"ok": True})


def _user_id_from(d):
    try:
        return int(str(d.get("id") or "").split("-")[1])
    except (ValueError, IndexError):
        return None


def _temporary_password():
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(12)) + "!" + str(secrets.randbelow(90) + 10)
        if any(c.isupper() for c in pw) and any(c.islower() for c in pw):
            return pw


@bp.route("/api/users/reset-password", methods=["POST"])
@permission_required("settings")
def api_users_reset_password():
    user_id = _user_id_from(request.get_json(silent=True) or {})
    if not user_id:
        return jsonify({"ok": False, "error": "Invalid user id."}), 400
    rows = execute_query(DB_CONFIG, "SELECT username FROM users WHERE user_id = %s;", (user_id,), fetch=True)
    if not rows:
        return jsonify({"ok": False, "error": "User not found."}), 404
    temp = _temporary_password()
    execute_query(DB_CONFIG, """
        UPDATE users SET password_hash = %s, must_change_password = TRUE,
               failed_attempts = 0, locked_until = NULL
        WHERE user_id = %s;
    """, (hash_password(temp), user_id))
    log_audit(DB_CONFIG, "PASSWORD_RESET", f"Reset the password of '{rows[0]['username']}'.",
              session["user"]["username"])
    return jsonify({"ok": True, "data": {"username": rows[0]["username"], "temporaryPassword": temp}})


@bp.route("/api/users/reset-2fa", methods=["POST"])
@permission_required("settings")
def api_users_reset_2fa():
    user_id = _user_id_from(request.get_json(silent=True) or {})
    if not user_id:
        return jsonify({"ok": False, "error": "Invalid user id."}), 400
    rows = execute_query(DB_CONFIG, "SELECT username FROM users WHERE user_id = %s;", (user_id,), fetch=True)
    if not rows:
        return jsonify({"ok": False, "error": "User not found."}), 404
    execute_query(DB_CONFIG, """
        UPDATE users SET totp_secret = NULL, totp_enabled = FALSE, totp_last_step = NULL WHERE user_id = %s;
    """, (user_id,))
    log_audit(DB_CONFIG, "2FA_RESET", f"Turned off two-factor authentication for '{rows[0]['username']}'.",
              session["user"]["username"])
    return jsonify({"ok": True})
