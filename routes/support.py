import hashlib
import re
import secrets

from flask import Blueprint, jsonify, request, session

import mailer
from config import DB_CONFIG
from db import execute_query, log_audit, get_company_settings
from auth import permission_required
from security import limiter

bp = Blueprint("support", __name__)

MESSAGE_MAX_LEN = 500
CONCERN_MAX_LEN = 2000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")
TICKET_RE = re.compile(r"^\s*(?:TKT-?)?0*(\d{1,9})\s*$", re.I)
TXN_RE = re.compile(r"^\s*(?:TXN-?)?0*(\d{1,9})\s*$", re.I)
STATUSES = ("Open", "Answered", "Closed")
REPLY_ROLES = ("System Administrator", "Operations Personnel")


def ticket_code(ticket_id):
    return f"TKT-{ticket_id:04d}"


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _iso(v):
    return v.isoformat() if v else None


def _clean(d, key, max_len):
    return (str(d.get(key) or "")).strip()[:max_len]


def _customer_ticket():
    token = request.headers.get("X-Support-Token", "")
    if not token or len(token) > 128:
        return None
    rows = execute_query(DB_CONFIG, "SELECT * FROM support_tickets WHERE token_hash = %s;",
                         (_hash(token),), fetch=True)
    return rows[0] if rows else None


def _messages(ticket_id, after=0):
    rows = execute_query(DB_CONFIG, """
        SELECT message_id, sender, staff_name, body, sent_at FROM support_messages
         WHERE ticket_id = %s AND message_id > %s ORDER BY message_id LIMIT 500;
    """, (ticket_id, after), fetch=True)
    return [{"id": r["message_id"], "sender": r["sender"], "staff": r["staff_name"] or "",
             "body": r["body"], "at": _iso(r["sent_at"])} for r in rows]


def _after():
    try:
        return max(int(request.args.get("after", 0)), 0)
    except ValueError:
        return 0


def _company_name():
    try:
        return get_company_settings(DB_CONFIG).get("company_name") or "Parabellum Steel & Iron Works"
    except Exception:
        return "Parabellum Steel & Iron Works"


def _ticket_public(t):
    return {"ticket": ticket_code(t["ticket_id"]), "status": t["status"], "name": t["contact_name"],
            "company": t["company"] or "", "createdAt": _iso(t["created_at"])}


# Customer side
@bp.route("/api/support/tickets", methods=["POST"])
@limiter.limit("5 per hour")
def api_support_create():
    d = request.get_json(silent=True) or {}
    if d.get("website"):
        return jsonify({"ok": False, "error": "Could not submit the request."}), 400
    company = _clean(d, "company", 150)
    name = _clean(d, "name", 120)
    email = _clean(d, "email", 150).lower()
    phone = _clean(d, "phone", 40)
    order_ref = _clean(d, "orderRef", 60)
    concern = (str(d.get("concern") or "")).strip()
    errors = {}
    if not name:
        errors["name"] = "Please enter your name."
    if not EMAIL_RE.match(email):
        errors["email"] = "Please enter a valid email address."
    if not PHONE_RE.match(phone):
        errors["phone"] = "Please enter a valid phone number."
    if len(concern) < 5:
        errors["concern"] = "Please describe your concern."
    elif len(concern) > CONCERN_MAX_LEN:
        errors["concern"] = f"Please keep it under {CONCERN_MAX_LEN} characters."
    if errors:
        return jsonify({"ok": False, "error": next(iter(errors.values())), "fields": errors}), 400

    txn_id = None
    m = TXN_RE.match(order_ref) if order_ref else None
    if m:
        rows = execute_query(DB_CONFIG, "SELECT transaction_id FROM transactions WHERE transaction_id = %s;",
                             (int(m.group(1)),), fetch=True)
        txn_id = rows[0]["transaction_id"] if rows else None

    token = secrets.token_urlsafe(32)
    rows = execute_query(DB_CONFIG, """
        INSERT INTO support_tickets (token_hash, company, contact_name, email, phone, order_ref, transaction_id,
                                     customer_read_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP) RETURNING *;
    """, (_hash(token), company or None, name, email, phone, order_ref or None, txn_id), fetch=True)
    t = rows[0]
    execute_query(DB_CONFIG, "INSERT INTO support_messages (ticket_id, sender, body) VALUES (%s, 'customer', %s);",
                  (t["ticket_id"], concern))
    code = ticket_code(t["ticket_id"])
    log_audit(DB_CONFIG, "SUPPORT_TICKET_NEW", f"{code} from {name}{' (' + company + ')' if company else ''}.", "customer")
    mailer.send_async(email, f"[{code}] We received your concern",
        f"Hi {name},\n\nThank you for reaching out to {_company_name()}. Your ticket number is {code}.\n\n"
        f"Our team will reply in the support chat on our website. To open it from another device, "
        f"click Need Support, then 'Already have a ticket?' and enter {code} with this email address.\n\n"
        f"Your concern:\n{concern}\n")
    return jsonify({"ok": True, "data": {**_ticket_public(t), "token": token}})


@bp.route("/api/support/open", methods=["POST"])
@limiter.limit("10 per minute;30 per hour")
def api_support_open():
    d = request.get_json(silent=True) or {}
    m = TICKET_RE.match(str(d.get("ticket") or ""))
    email = _clean(d, "email", 150).lower()
    rows = execute_query(DB_CONFIG, "SELECT * FROM support_tickets WHERE ticket_id = %s AND email = %s;",
                         (int(m.group(1)), email), fetch=True) if m and email else []
    if not rows:
        return jsonify({"ok": False, "error": "No ticket matches that ticket number and email."}), 404
    token = secrets.token_urlsafe(32)
    execute_query(DB_CONFIG, "UPDATE support_tickets SET token_hash = %s WHERE ticket_id = %s;",
                  (_hash(token), rows[0]["ticket_id"]))
    return jsonify({"ok": True, "data": {**_ticket_public(rows[0]), "token": token}})


@bp.route("/api/support/thread")
@limiter.limit("40 per minute")
def api_support_thread():
    t = _customer_ticket()
    if not t:
        return jsonify({"ok": False, "error": "Ticket not found. It may have been opened on another device."}), 404
    msgs = _messages(t["ticket_id"], _after())
    if any(x["sender"] == "staff" for x in msgs):
        execute_query(DB_CONFIG, "UPDATE support_tickets SET customer_read_at = CURRENT_TIMESTAMP WHERE ticket_id = %s;",
                      (t["ticket_id"],))
    return jsonify({"ok": True, "data": {**_ticket_public(t), "messages": msgs}})


@bp.route("/api/support/unread")
@limiter.limit("20 per minute")
def api_support_unread():
    t = _customer_ticket()
    if not t:
        return jsonify({"ok": True, "data": {"unread": 0}})
    rows = execute_query(DB_CONFIG, """
        SELECT COUNT(*) AS n FROM support_messages
         WHERE ticket_id = %s AND sender = 'staff' AND sent_at > COALESCE(%s, 'epoch'::timestamptz);
    """, (t["ticket_id"], t["customer_read_at"]), fetch=True)
    return jsonify({"ok": True, "data": {"unread": int(rows[0]["n"])}})


@bp.route("/api/support/message", methods=["POST"])
@limiter.limit("20 per minute")
def api_support_message():
    t = _customer_ticket()
    if not t:
        return jsonify({"ok": False, "error": "Ticket not found. It may have been opened on another device."}), 404
    body = (str((request.get_json(silent=True) or {}).get("message") or "")).strip()
    if not body:
        return jsonify({"ok": False, "error": "Message is empty."}), 400
    if len(body) > MESSAGE_MAX_LEN:
        return jsonify({"ok": False, "error": f"Messages can be up to {MESSAGE_MAX_LEN} characters."}), 400
    execute_query(DB_CONFIG, "INSERT INTO support_messages (ticket_id, sender, body) VALUES (%s, 'customer', %s);",
                  (t["ticket_id"], body))
    execute_query(DB_CONFIG, """
        UPDATE support_tickets SET status = 'Open', updated_at = CURRENT_TIMESTAMP,
               closed_at = NULL, closed_by = NULL WHERE ticket_id = %s;
    """, (t["ticket_id"],))
    return jsonify({"ok": True})


# Staff side
def unread_ticket_count():
    rows = execute_query(DB_CONFIG, """
        SELECT COUNT(DISTINCT t.ticket_id) AS n
          FROM support_tickets t JOIN support_messages m ON m.ticket_id = t.ticket_id
         WHERE m.sender = 'customer' AND m.sent_at > COALESCE(t.staff_read_at, 'epoch'::timestamptz);
    """, fetch=True)
    return int(rows[0]["n"]) if rows else 0


def _can_reply():
    return session["user"]["role"] in REPLY_ROLES


def _ticket_id(raw):
    m = TICKET_RE.match(str(raw))
    return int(m.group(1)) if m else None


@bp.route("/api/support/admin/tickets")
@permission_required("support")
def api_support_admin_list():
    rows = execute_query(DB_CONFIG, """
        SELECT t.ticket_id, t.company, t.contact_name, t.email, t.status, t.updated_at, t.created_at, t.order_ref,
               lm.body AS last_body, lm.sender AS last_sender, lm.sent_at AS last_at,
               COALESCE(un.n, 0) AS unread
          FROM support_tickets t
          LEFT JOIN LATERAL (SELECT body, sender, sent_at FROM support_messages
                              WHERE ticket_id = t.ticket_id ORDER BY message_id DESC LIMIT 1) lm ON TRUE
          LEFT JOIN LATERAL (SELECT COUNT(*) AS n FROM support_messages
                              WHERE ticket_id = t.ticket_id AND sender = 'customer'
                                AND sent_at > COALESCE(t.staff_read_at, 'epoch'::timestamptz)) un ON TRUE
         ORDER BY (t.status = 'Closed'), COALESCE(lm.sent_at, t.updated_at) DESC
         LIMIT 500;
    """, fetch=True)
    tickets = [{
        "id": r["ticket_id"], "ticket": ticket_code(r["ticket_id"]), "company": r["company"] or "",
        "name": r["contact_name"], "email": r["email"], "status": r["status"], "orderRef": r["order_ref"] or "",
        "last": r["last_body"] or "", "lastSender": r["last_sender"], "lastAt": _iso(r["last_at"] or r["updated_at"]),
        "unread": int(r["unread"]),
    } for r in rows]
    summary = {s: sum(1 for t in tickets if t["status"] == s) for s in STATUSES}
    summary["unread"] = sum(1 for t in tickets if t["unread"])
    return jsonify({"ok": True, "data": {"tickets": tickets, "summary": summary, "canReply": _can_reply()}})


@bp.route("/api/support/admin/tickets/<tid>")
@permission_required("support")
def api_support_admin_ticket(tid):
    ticket_id = _ticket_id(tid)
    rows = execute_query(DB_CONFIG, """
        SELECT t.*, tx.customer_name AS txn_customer, tx.txn_date, tx.amount, tx.payment_status
          FROM support_tickets t LEFT JOIN transactions tx ON tx.transaction_id = t.transaction_id
         WHERE t.ticket_id = %s;
    """, (ticket_id,), fetch=True) if ticket_id else []
    if not rows:
        return jsonify({"ok": False, "error": "Ticket not found."}), 404
    t = rows[0]
    msgs = _messages(ticket_id, _after())
    if any(x["sender"] == "customer" for x in msgs):
        execute_query(DB_CONFIG, "UPDATE support_tickets SET staff_read_at = CURRENT_TIMESTAMP WHERE ticket_id = %s;",
                      (ticket_id,))
    return jsonify({"ok": True, "data": {
        "id": ticket_id, "ticket": ticket_code(ticket_id), "status": t["status"],
        "company": t["company"] or "", "name": t["contact_name"], "email": t["email"], "phone": t["phone"],
        "orderRef": t["order_ref"] or "", "createdAt": _iso(t["created_at"]),
        "closedAt": _iso(t["closed_at"]), "closedBy": t["closed_by"] or "",
        "customerReadAt": _iso(t["customer_read_at"]),
        "transaction": None if not t["transaction_id"] else {
            "id": f"TXN-{t['transaction_id']:04d}", "customer": t["txn_customer"] or "",
            "date": str(t["txn_date"]) if t["txn_date"] else "", "amount": float(t["amount"] or 0),
            "status": t["payment_status"] or "Pending"},
        "messages": msgs, "canReply": _can_reply(),
    }})


@bp.route("/api/support/admin/tickets/<tid>/reply", methods=["POST"])
@permission_required("support")
@limiter.limit("60 per minute")
def api_support_admin_reply(tid):
    if not _can_reply():
        return jsonify({"ok": False, "error": "Your role can view tickets but not reply."}), 403
    ticket_id = _ticket_id(tid)
    body = (str((request.get_json(silent=True) or {}).get("message") or "")).strip()
    if not body:
        return jsonify({"ok": False, "error": "Message is empty."}), 400
    if len(body) > MESSAGE_MAX_LEN:
        return jsonify({"ok": False, "error": f"Messages can be up to {MESSAGE_MAX_LEN} characters."}), 400
    rows = execute_query(DB_CONFIG, """
        UPDATE support_tickets SET status = 'Answered', updated_at = CURRENT_TIMESTAMP,
               staff_read_at = CURRENT_TIMESTAMP, closed_at = NULL, closed_by = NULL
         WHERE ticket_id = %s RETURNING contact_name, email;
    """, (ticket_id,), fetch=True) if ticket_id else []
    if not rows:
        return jsonify({"ok": False, "error": "Ticket not found."}), 404
    u = session["user"]
    execute_query(DB_CONFIG, """
        INSERT INTO support_messages (ticket_id, sender, staff_user_id, staff_name, body)
        VALUES (%s, 'staff', %s, %s, %s);
    """, (ticket_id, u.get("user_id"), u.get("name"), body))
    code = ticket_code(ticket_id)
    mailer.send_async(rows[0]["email"], f"[{code}] New reply from {_company_name()}",
        f"Hi {rows[0]['contact_name']},\n\n{u.get('name')} replied to your ticket {code}:\n\n{body}\n\n"
        f"You can continue the conversation in the support chat on our website.\n")
    return jsonify({"ok": True})


@bp.route("/api/support/admin/tickets/<tid>/status", methods=["POST"])
@permission_required("support")
def api_support_admin_status(tid):
    if not _can_reply():
        return jsonify({"ok": False, "error": "Your role can view tickets but not change them."}), 403
    ticket_id = _ticket_id(tid)
    status = (request.get_json(silent=True) or {}).get("status")
    if status not in ("Open", "Closed"):
        return jsonify({"ok": False, "error": "Status must be Open or Closed."}), 400
    u = session["user"]
    rows = execute_query(DB_CONFIG, """
        UPDATE support_tickets SET status = %s, updated_at = CURRENT_TIMESTAMP,
               closed_at = CASE WHEN %s = 'Closed' THEN CURRENT_TIMESTAMP END,
               closed_by = CASE WHEN %s = 'Closed' THEN %s END
         WHERE ticket_id = %s RETURNING ticket_id;
    """, (status, status, status, u.get("name"), ticket_id), fetch=True) if ticket_id else []
    if not rows:
        return jsonify({"ok": False, "error": "Ticket not found."}), 404
    log_audit(DB_CONFIG, "SUPPORT_TICKET_" + ("CLOSED" if status == "Closed" else "REOPENED"),
              f"{ticket_code(ticket_id)} marked {status}.", u.get("username"))
    return jsonify({"ok": True, "data": {"status": status}})
