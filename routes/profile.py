import os
import re

from flask import Blueprint, jsonify, request, session, url_for
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

from config import DB_CONFIG
from db import execute_query, log_audit
from auth import login_required, hash_password
import preferences
import totp

bp = Blueprint("profile", __name__)


@bp.route("/api/profile")
@login_required
def api_profile():
    uid = session["user"]["user_id"]
    username = session["user"]["username"]

    rows = execute_query(DB_CONFIG, """
        SELECT user_id, username, full_name, email, department, role
        FROM users WHERE user_id = %s;
    """, (uid,), fetch=True)
    if not rows:
        return jsonify({"ok": False, "error": "Account not found."}), 404
    u = rows[0]

    counts = execute_query(DB_CONFIG, """
        SELECT COUNT(*) FILTER (WHERE action = 'LOGIN_SUCCESS')   AS logins,
               COUNT(*) FILTER (WHERE action = 'REPORT_EXPORTED') AS reports,
               COUNT(*) FILTER (WHERE action = 'RUN_FORECAST')    AS forecasts
        FROM audit_logs WHERE username = %s;
    """, (username,), fetch=True)[0]

    recent = execute_query(DB_CONFIG, """
        SELECT action, details, logged_at FROM audit_logs
        WHERE username = %s ORDER BY log_id DESC LIMIT 6;
    """, (username,), fetch=True)

    week = execute_query(DB_CONFIG, """
        SELECT to_char(d, 'Dy') AS label, COUNT(a.log_id) AS n
        FROM generate_series((CURRENT_DATE - 6)::timestamp, CURRENT_DATE::timestamp,
                             interval '1 day') AS d
        LEFT JOIN audit_logs a
               ON a.username = %s AND a.logged_at::date = d::date
        GROUP BY d ORDER BY d;
    """, (username,), fetch=True)

    return jsonify({"ok": True, "data": {
        "userCode": f"USR-{u['user_id']:02d}",
        "username": u["username"],
        "name": u["full_name"] or u["username"],
        "email": u["email"] or "",
        "department": u["department"] or "",
        "role": u["role"],
        "stats": {"logins": int(counts["logins"]), "reports": int(counts["reports"]),
                  "forecasts": int(counts["forecasts"])},
        "recent": [{
            "action": r["action"], "details": r["details"] or "",
            "time": r["logged_at"].strftime("%b %d, %Y %H:%M") if r["logged_at"] else "",
        } for r in recent],
        "week": [{"label": r["label"], "n": int(r["n"])} for r in week],
    }})


# Profile avatar upload

ALLOWED_AVATAR_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}
AVATAR_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "static", "uploads", "avatars")

_AVATAR_MAGIC_BYTES = {
    "png":  [b"\x89PNG\r\n\x1a\n"],
    "jpg":  [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif":  [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],
}


def _content_matches_extension(file_storage, ext):
    header = file_storage.stream.read(16)
    file_storage.stream.seek(0)
    if not header:
        return False
    signatures = _AVATAR_MAGIC_BYTES.get(ext, [])
    if not any(header.startswith(sig) for sig in signatures):
        return False
    if ext == "webp":
        return len(header) >= 12 and header[8:12] == b"WEBP"
    return True


@bp.route("/api/profile/avatar", methods=["POST"])
@login_required
def api_profile_avatar():
    file = request.files.get("photo")
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "No file received."}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_AVATAR_EXTS:
        return jsonify({"ok": False, "error": "Only PNG, JPG, GIF, or WEBP images are allowed."}), 400

    if not _content_matches_extension(file, ext):
        log_audit(DB_CONFIG, "AVATAR_REJECTED",
                  f"Uploaded file's content did not match its .{ext} extension.",
                  session.get("user", {}).get("username", "unknown"))
        return jsonify({"ok": False, "error": "That file doesn't look like a valid image. Please upload a real PNG, JPG, GIF, or WEBP."}), 400

    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > 3 * 1024 * 1024:
        return jsonify({"ok": False, "error": "Image must be under 3 MB."}), 400

    os.makedirs(AVATAR_DIR, exist_ok=True)
    user_id = session["user"]["user_id"]
    fname = secure_filename(f"user_{user_id}.{ext}")
    for old_ext in ALLOWED_AVATAR_EXTS:
        old_path = os.path.join(AVATAR_DIR, f"user_{user_id}.{old_ext}")
        if os.path.exists(old_path) and old_ext != ext:
            os.remove(old_path)
    file.save(os.path.join(AVATAR_DIR, fname))

    url = url_for("static", filename=f"uploads/avatars/{fname}")
    execute_query(DB_CONFIG, "UPDATE users SET avatar_path=%s WHERE user_id=%s;",
                 (url, user_id))
    session["user"]["avatar_path"] = url
    log_audit(DB_CONFIG, "AVATAR_UPDATED", "Profile photo updated.",
              session["user"]["username"])
    return jsonify({"ok": True, "url": url})


@bp.route("/api/profile/save", methods=["POST"])
@login_required
def api_profile_save():
    d = request.get_json(silent=True) or {}
    name = (d.get("name") or "").strip()
    email = (d.get("email") or "").strip()
    department = (d.get("department") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Full name is required."}), 400
    if len(name) > 120 or len(email) > 150 or len(department) > 80:
        return jsonify({"ok": False, "error": "One of the fields is too long."}), 400
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        return jsonify({"ok": False, "error": "Please enter a valid email address."}), 400

    uid = session["user"]["user_id"]
    execute_query(DB_CONFIG, "UPDATE users SET full_name=%s, email=%s, department=%s WHERE user_id=%s;",
                  (name, email or None, department or None, uid))
    user = dict(session["user"])
    user["name"] = name
    session["user"] = user
    log_audit(DB_CONFIG, "PROFILE_UPDATED", "Updated profile details.", session["user"]["username"])
    return jsonify({"ok": True, "data": {"name": name, "email": email, "department": department}})


@bp.route("/api/profile/preferences")
@login_required
def api_preferences_get():
    return jsonify({"ok": True, "data": preferences.load(DB_CONFIG, session["user"]["user_id"])})


@bp.route("/api/profile/preferences", methods=["POST"])
@login_required
def api_preferences_save():
    uid = session["user"]["user_id"]
    current = preferences.load(DB_CONFIG, uid)
    updated = preferences.merge(current, request.get_json(silent=True) or {})
    preferences.save(DB_CONFIG, uid, updated)
    return jsonify({"ok": True, "data": updated})


@bp.route("/api/profile/password", methods=["POST"])
@login_required
def api_profile_password():
    d = request.get_json(silent=True) or {}
    current = d.get("current") or ""
    new = d.get("new") or ""
    if not current or not new:
        return jsonify({"ok": False, "error": "Please fill in all password fields."}), 400
    if new != (d.get("confirm") or ""):
        return jsonify({"ok": False, "error": "New passwords do not match."}), 400
    uid = session["user"]["user_id"]
    rows = execute_query(DB_CONFIG, "SELECT password_hash FROM users WHERE user_id = %s;", (uid,), fetch=True)
    if not rows or not check_password_hash(rows[0]["password_hash"], current):
        log_audit(DB_CONFIG, "PASSWORD_CHANGE_FAILED", "Wrong current password.", session["user"]["username"])
        return jsonify({"ok": False, "error": "Current password is incorrect."}), 400
    if check_password_hash(rows[0]["password_hash"], new):
        return jsonify({"ok": False, "error": "New password must be different from the current one."}), 400
    try:
        new_hash = hash_password(new)
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    execute_query(DB_CONFIG, "UPDATE users SET password_hash = %s, must_change_password = FALSE WHERE user_id = %s;",
                  (new_hash, uid))
    user = dict(session["user"])
    user["must_change_password"] = False
    session["user"] = user
    log_audit(DB_CONFIG, "PASSWORD_CHANGED", "Changed own password.", session["user"]["username"])
    return jsonify({"ok": True})


def _set_session_flag(key, value):
    user = dict(session["user"])
    user[key] = value
    session["user"] = user


@bp.route("/api/profile/2fa/setup", methods=["POST"])
@login_required
def api_2fa_setup():
    if session["user"].get("two_factor"):
        return jsonify({"ok": False, "error": "Two-factor authentication is already on."}), 400
    secret = totp.generate_secret()
    session["pending_totp"] = secret
    return jsonify({"ok": True, "data": {
        "secret": secret,
        "uri": totp.provisioning_uri(session["user"]["username"], secret),
    }})


@bp.route("/api/profile/2fa/enable", methods=["POST"])
@login_required
def api_2fa_enable():
    secret = session.get("pending_totp")
    if not secret:
        return jsonify({"ok": False, "error": "Start the setup again."}), 400
    step = totp.verify(secret, (request.get_json(silent=True) or {}).get("code"))
    if step is None:
        return jsonify({"ok": False, "error": "That code is not correct. Check the time on your phone and try again."}), 400
    execute_query(DB_CONFIG, """
        UPDATE users SET totp_secret = %s, totp_enabled = TRUE, totp_last_step = %s WHERE user_id = %s;
    """, (secret, step, session["user"]["user_id"]))
    session.pop("pending_totp", None)
    _set_session_flag("two_factor", True)
    log_audit(DB_CONFIG, "2FA_ENABLED", "Turned on two-factor authentication.", session["user"]["username"])
    return jsonify({"ok": True})


@bp.route("/api/profile/2fa/disable", methods=["POST"])
@login_required
def api_2fa_disable():
    d = request.get_json(silent=True) or {}
    uid = session["user"]["user_id"]
    rows = execute_query(DB_CONFIG, """
        SELECT password_hash, totp_secret, totp_last_step FROM users WHERE user_id = %s;
    """, (uid,), fetch=True)
    if not rows or not check_password_hash(rows[0]["password_hash"], d.get("password") or ""):
        return jsonify({"ok": False, "error": "Password is incorrect."}), 400
    if totp.verify(rows[0]["totp_secret"], d.get("code"), rows[0]["totp_last_step"]) is None:
        return jsonify({"ok": False, "error": "Authenticator code is not correct."}), 400
    execute_query(DB_CONFIG, """
        UPDATE users SET totp_secret = NULL, totp_enabled = FALSE, totp_last_step = NULL WHERE user_id = %s;
    """, (uid,))
    _set_session_flag("two_factor", False)
    log_audit(DB_CONFIG, "2FA_DISABLED", "Turned off two-factor authentication.", session["user"]["username"])
    return jsonify({"ok": True})
