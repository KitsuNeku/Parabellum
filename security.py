import hmac
import secrets

from flask import request, jsonify, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    default_limits=["200 per minute", "3000 per hour"],
    storage_uri="memory://",
)


MAX_JSON_BYTES          = 25 * 1024 * 1024
MAX_USERNAME_LEN       = 60
MAX_PASSWORD_LEN       = 256
MAX_STRING_FIELD_LEN   = 500
MAX_TEXT_FIELD_LEN     = 4000

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_TOKEN_BYTES = 32
CSRF_SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}

CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'"
)


def apply_security(app):

    @app.after_request
    def _add_security_headers(resp):
        resp.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        resp.headers["Content-Security-Policy"] = CSP

        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        resp.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        path = request.path or ""
        if path.startswith("/api/") or session.get("user"):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Pragma"] = "no-cache"

        resp.headers.pop("Server", None)
        return resp

    # 2) Request-size cap
    app.config["MAX_CONTENT_LENGTH"] = MAX_JSON_BYTES

    @app.errorhandler(413)
    def _too_large(e):
        return jsonify({"ok": False, "error": "Request too large."}), 413

    # 3) Rate limiting
    limiter.init_app(app)

    @app.errorhandler(429)
    def _rate_limited(e):
        _log_security_event("RATE_LIMITED", f"{request.method} {request.path}")
        return jsonify({
            "ok": False,
            "error": "Too many requests. Please slow down and try again shortly.",
        }), 429

    # 4) Session hygiene
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True

    @app.before_request
    def _cap_string_fields():
        if not request.is_json:
            return
        try:
            data = request.get_json(silent=True) or {}
        except Exception:
            return
        for key, value in _iter_strings(data):
            limit = (MAX_PASSWORD_LEN if key == "password"
                     else MAX_USERNAME_LEN if key == "username"
                     else MAX_TEXT_FIELD_LEN if key in ("remarks", "description", "notes", "address", "concern")
                     else MAX_JSON_BYTES if key == "sql"
                     else MAX_STRING_FIELD_LEN)
            if len(value) > limit:
                return jsonify({
                    "ok": False,
                    "error": f"'{key}' is too long (max {limit} characters).",
                }), 400

    @app.before_request
    def _enforce_json_content_type():
        if request.method in CSRF_SAFE_METHODS:
            return
        if not (request.path or "").startswith("/api/"):
            return
        if request.content_length in (None, 0):
            return
        ct = (request.content_type or "").split(";")[0].strip().lower()
        if ct != "application/json":
            _log_security_event(
                "CONTENT_TYPE_REJECTED",
                f"{request.method} {request.path} had Content-Type '{request.content_type}'.")
            return jsonify({
                "ok": False,
                "error": "API requests must have Content-Type: application/json.",
            }), 415


    @app.after_request
    def _issue_csrf_cookie(resp):
        token = session.get("_csrf")
        if not token:
            token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
            session["_csrf"] = token
        resp.set_cookie(
            CSRF_COOKIE_NAME, token,
            secure=app.config.get("SESSION_COOKIE_SECURE", False),
            httponly=False,
            samesite="Lax",
            path="/",
        )
        return resp

    @app.before_request
    def _verify_csrf():
        if request.method in CSRF_SAFE_METHODS:
            return
        path = request.path or ""
        if not path.startswith("/api/"):
            return
        if path in ("/api/login",):
            return

        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        session_token = session.get("_csrf", "")

        if not (header_token and cookie_token and session_token):
            _log_security_event("CSRF_REJECTED", f"{request.method} {path}: token missing.")
            return jsonify({"ok": False, "error": "CSRF token missing."}), 403
        if not (hmac.compare_digest(header_token, cookie_token)
                and hmac.compare_digest(header_token, session_token)):
            _log_security_event("CSRF_REJECTED", f"{request.method} {path}: token mismatch.")
            return jsonify({"ok": False, "error": "CSRF token mismatch."}), 403

    return limiter


def _log_security_event(action, details):
    try:
        from db import log_audit
        from config import DB_CONFIG
        ip = get_remote_address()
        log_audit(DB_CONFIG, action, f"{details} (ip={ip})")
    except Exception:
        pass


def _iter_strings(obj, key=None):
    if isinstance(obj, str):
        yield key or "", obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, key=k)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_strings(item, key=key)

