from flask import Blueprint, jsonify, request, session, current_app

from config import DB_CONFIG
from db import execute_query
from auth import login_required
from security import limiter

bp = Blueprint("chat", __name__)


CHAT_MAX_LEN = 500


def _chat_rate_key():
    u = session.get("user") or {}
    return f"chat:{u.get('user_id', request.remote_addr)}"


def _chat_iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else (None if v is None else str(v))


def _chat_failure(e):
    current_app.logger.exception("Chat error")
    if "chat_messages" in str(e) and "does not exist" in str(e):
        return jsonify({"ok": False, "error":
            "Chat is not set up yet. Run migrations/014_add_chat_messages.sql once on the database."}), 503
    return jsonify({"ok": False, "error": "A server error occurred. Please try again or contact your administrator."}), 500


@bp.route("/api/chat/unread")
@login_required
@limiter.limit("30 per minute", key_func=_chat_rate_key)
def api_chat_unread():
    try:
        me = int(session["user"]["user_id"])
        rows = execute_query(DB_CONFIG,
            "SELECT COUNT(*) AS n FROM chat_messages WHERE recipient_id = %s AND read_at IS NULL;",
            (me,), fetch=True)
        return jsonify({"ok": True, "data": {"unread": int(rows[0]["n"]) if rows else 0}})
    except Exception as e:
        return _chat_failure(e)


@bp.route("/api/chat/contacts")
@login_required
@limiter.limit("30 per minute", key_func=_chat_rate_key)
def api_chat_contacts():
    try:
        me = int(session["user"]["user_id"])
        rows = execute_query(DB_CONFIG, """
            SELECT u.user_id, COALESCE(NULLIF(u.full_name, ''), u.username) AS name,
                   u.role, u.department,
                   COALESCE(un.n, 0) AS unread,
                   lm.body AS last_body, lm.sent_at AS last_at, lm.sender_id AS last_sender
              FROM users u
              LEFT JOIN (SELECT sender_id, COUNT(*) AS n
                           FROM chat_messages
                          WHERE recipient_id = %s AND read_at IS NULL
                          GROUP BY sender_id) un ON un.sender_id = u.user_id
              LEFT JOIN LATERAL (SELECT body, sent_at, sender_id
                                   FROM chat_messages
                                  WHERE (sender_id = u.user_id AND recipient_id = %s)
                                     OR (sender_id = %s AND recipient_id = u.user_id)
                                  ORDER BY message_id DESC LIMIT 1) lm ON TRUE
             WHERE u.is_active AND u.user_id <> %s
             ORDER BY lm.sent_at DESC NULLS LAST, name;
        """, (me, me, me, me), fetch=True)
        data = [{
            "id":         r["user_id"],
            "name":       r["name"],
            "role":       r["role"],
            "department": r["department"] or "",
            "unread":     int(r["unread"] or 0),
            "lastBody":   (r["last_body"] or "")[:120],
            "lastAt":     _chat_iso(r["last_at"]),
            "lastMine":   r["last_sender"] == me if r["last_sender"] is not None else False,
        } for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return _chat_failure(e)


@bp.route("/api/chat/messages")
@login_required
@limiter.limit("60 per minute", key_func=_chat_rate_key)
def api_chat_messages():
    try:
        me = int(session["user"]["user_id"])
        other = request.args.get("with", type=int)
        after = request.args.get("after", default=0, type=int) or 0
        if not other or other == me:
            return jsonify({"ok": False, "error": "Choose someone to chat with."}), 400
        if not execute_query(DB_CONFIG,
                "SELECT 1 FROM users WHERE user_id = %s AND is_active;", (other,), fetch=True):
            return jsonify({"ok": False, "error": "That account is not available."}), 404

        rows = execute_query(DB_CONFIG, """
            SELECT * FROM (
                SELECT message_id, sender_id, body, sent_at
                  FROM chat_messages
                 WHERE ((sender_id = %s AND recipient_id = %s) OR (sender_id = %s AND recipient_id = %s))
                   AND message_id > %s
                 ORDER BY message_id DESC LIMIT 100) latest
            ORDER BY message_id;
        """, (me, other, other, me, after), fetch=True)

        execute_query(DB_CONFIG, """
            UPDATE chat_messages SET read_at = CURRENT_TIMESTAMP
             WHERE recipient_id = %s AND sender_id = %s AND read_at IS NULL;
        """, (me, other))

        data = [{"id": r["message_id"], "mine": r["sender_id"] == me,
                 "body": r["body"], "sentAt": _chat_iso(r["sent_at"])} for r in rows]
        return jsonify({"ok": True, "data": data})
    except Exception as e:
        return _chat_failure(e)


@bp.route("/api/chat/send", methods=["POST"])
@login_required
@limiter.limit("30 per minute", key_func=_chat_rate_key)
def api_chat_send():
    try:
        me = int(session["user"]["user_id"])
        d = request.get_json(silent=True) or {}
        try:
            to = int(d.get("to"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Choose someone to message."}), 400
        body = d.get("body")
        body = body.strip() if isinstance(body, str) else ""
        if not body:
            return jsonify({"ok": False, "error": "Type a message first."}), 400
        if len(body) > CHAT_MAX_LEN:
            return jsonify({"ok": False, "error": f"Messages can be up to {CHAT_MAX_LEN} characters."}), 400
        if to == me:
            return jsonify({"ok": False, "error": "You can't message yourself."}), 400
        if not execute_query(DB_CONFIG,
                "SELECT 1 FROM users WHERE user_id = %s AND is_active;", (to,), fetch=True):
            return jsonify({"ok": False, "error": "That account is not available."}), 404

        row = execute_query(DB_CONFIG, """
            INSERT INTO chat_messages (sender_id, recipient_id, body)
            VALUES (%s, %s, %s) RETURNING message_id, sent_at;
        """, (me, to, body), fetch=True)[0]
        return jsonify({"ok": True, "data": {"id": row["message_id"], "mine": True,
                                             "body": body, "sentAt": _chat_iso(row["sent_at"])}})
    except Exception as e:
        return _chat_failure(e)
