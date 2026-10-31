import os
from datetime import timedelta

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from config import (SECRET_KEY, DEBUG, DB_CONFIG, AUTO_RETRAIN_ENABLED, AUTO_RETRAIN_HOUR,
                    AUTO_AGGREGATE_BEFORE_RETRAIN)
from db import execute_query, get_company_settings, get_security_settings
import preferences
import mailer
from auth import PAGES, allowed_pages, permission_required, needs_2fa_setup
from security import apply_security
import scheduler as retrain_scheduler
from routes import (auth_api, dashboard, chat, profile, inventory, suppliers, customers,
                    projects, transactions, users, settings, reports, forecast, outlook, support)

GENERIC_ERROR = "A server error occurred. Please try again or contact your administrator."

app = Flask(__name__)
app.secret_key = SECRET_KEY

if os.getenv("TRUST_PROXY", "0") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

apply_security(app)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "0") == "1",
)

for module in (auth_api, dashboard, chat, profile, inventory, suppliers, customers,
               projects, transactions, users, settings, reports, forecast, outlook, support):
    app.register_blueprint(module.bp)


@app.before_request
def apply_session_timeout():
    minutes = get_security_settings(DB_CONFIG)["session_timeout_min"]
    app.permanent_session_lifetime = timedelta(minutes=minutes)


# Error handling
@app.errorhandler(Exception)
def handle_unexpected_error(e):
    if isinstance(e, HTTPException):
        return e
    app.logger.exception("Unhandled error on %s %s", request.method, request.path)
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": GENERIC_ERROR}), 500
    return "A server error occurred.", 500


# Page routes
def _out_of_stock_count():
    try:
        rows = execute_query(DB_CONFIG,
                             "SELECT COUNT(*) AS n FROM materials WHERE current_stock <= 0;",
                             fetch=True)
        return int(rows[0]["n"]) if rows else 0
    except Exception:
        return 0


def _outlook_alert_count():
    try:
        rows = execute_query(DB_CONFIG, """
            SELECT (SELECT COUNT(*) FROM materials
                     WHERE current_stock <= 0 OR (critical_level > 0 AND current_stock <= critical_level))
                 + (SELECT COUNT(*) FROM stock_movements
                     WHERE movement_type = 'ISSUANCE' AND delivery_failed_at IS NOT NULL AND returned_at IS NULL) AS n;
        """, fetch=True)
        return int(rows[0]["n"]) if rows else 0
    except Exception:
        return 0


def _support_unread_count():
    try:
        return support.unread_ticket_count()
    except Exception:
        return 0


def _user_context():
    u = session.get("user") or {}
    name = u.get("name", "")
    initials = "".join(w[0] for w in name.split()).upper()[:2] if name else "?"
    allowed = allowed_pages()
    prefs = preferences.load(DB_CONFIG, u.get("user_id"))
    return {
        "current_user": u,
        "force_2fa": needs_2fa_setup(DB_CONFIG, u) if u else False,
        "email_ready": mailer.is_configured(),
        "prefs": prefs,
        "accent": preferences.ACCENTS[prefs["accent"]],
        "current_user_initials": initials,
        "allowed_pages": allowed,
        "inventory_oos_count": _out_of_stock_count() if "inventory" in allowed else 0,
        "outlook_alert_count": _outlook_alert_count() if "outlook" in allowed else 0,
        "support_unread_count": _support_unread_count() if "support" in allowed else 0,
    }


@app.context_processor
def inject_company():
    return {"company": get_company_settings(DB_CONFIG)}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/login")
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


def _make_page(name):
    @permission_required(name)
    def view():
        return render_template(f"{name}.html", active_page=name, **_user_context())
    view.__name__ = name
    return view


for _page in PAGES:
    app.add_url_rule(f"/{_page}", _page, _make_page(_page))


# Nightly retrain scheduler
if AUTO_RETRAIN_ENABLED and (not DEBUG or os.environ.get("WERKZEUG_RUN_MAIN") == "true"):
    retrain_scheduler.start(DB_CONFIG, hour=AUTO_RETRAIN_HOUR,
                            auto_aggregate=AUTO_AGGREGATE_BEFORE_RETRAIN)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=DEBUG)
