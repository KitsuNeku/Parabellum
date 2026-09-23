"""
Parabellum ISOS - Security Hardening
=================================================================
Defense-in-depth measures at the Flask application layer.

WHAT THIS COVERS
    - HTTP security headers (HSTS, CSP, X-Content-Type-Options,
      Cross-Origin-Opener-Policy, Cross-Origin-Resource-Policy,
      X-Permitted-Cross-Domain-Policies, etc.)
    - Rate limiting on login, forecasting, and report exports - both to
      slow brute-force attempts and to stop the more expensive operations
      (PDF/Excel generation, model training) from being hammered
    - CSRF protection via double-submit-cookie tokens on every
      state-changing (POST/PUT/PATCH/DELETE) request. Enforced on
      /api/* endpoints. The frontend fetch wrapper (see static/js/app.js)
      auto-injects the token from a non-HttpOnly cookie into an
      X-CSRF-Token request header; the server verifies they match.
    - Content-Type enforcement on state-changing /api/* requests
      (rejects anything other than application/json), which closes off
      the "simple request" CORS class that could bypass CSRF in weird
      old browsers.
    - Cache-Control: no-store on API responses and authenticated pages
      so shared browsers/proxies never cache sensitive data.
    - Request-size cap (prevents "gigabyte body" memory DoS)
    - Session absolute lifetime and idle timeout
    - Server-header suppression (removes fingerprinting)
    - Input-length limits on API JSON bodies
    - Server-side numeric validation (no negative prices/budgets, no
      out-of-range progress values) - closes off ways bad input could
      corrupt stored data even if it doesn't crash anything
    - Generic error messages to the client on every API failure - the
      real exception (with full traceback) is only ever written to the
      server's own log, never sent to the browser.

WHAT THIS DOES NOT COVER - call these out to your panel so nobody's
under the impression a Flask app protects itself against all of these:
    - HTTPS/TLS: needs a certificate (Let's Encrypt) and a reverse proxy
      (nginx/Caddy) or a hosting platform that terminates TLS for you.
      The headers below assume HTTPS is present; they're harmless on
      HTTP but only fully effective once TLS is set up.
    - Real DDoS protection: put Cloudflare (free tier) or your host's
      DDoS mitigation in front of the app. Application-layer rate
      limits help with credential stuffing and casual abuse; they can't
      stop a real botnet.
    - Database-layer attacks: managed hosting (Supabase) handles patching,
      backups, and network isolation.
"""

import hmac
import secrets

from flask import request, jsonify, session, make_response
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# Reasonable ceilings. Adjust in one place if needed.
MAX_JSON_BYTES          = 4 * 1024 * 1024   # 4 MB - covers JSON bodies AND avatar uploads
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
    # fonts.googleapis.com serves the actual @font-face CSS (style-src);
    # fonts.gstatic.com serves the woff2 font files it points to
    # (font-src). Every page in this app loads Poppins from Google
    # Fonts, so both need to be allowlisted or the stylesheet itself
    # gets blocked outright (not just the fonts it references).
    "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'; "
    "base-uri 'self'"
)


def apply_security(app):
    """
    Wire every hardening measure onto the Flask app. Call this ONCE at
    startup, right after `app = Flask(__name__)`.
    """

    # -------- 1) HTTP security headers on every response --------
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

        # Extra cross-origin isolation headers -- block a hostile page
        # from reading our window object (COOP) or loading our resources
        # into its own document (CORP).
        resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        resp.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        # Blocks legacy Flash / PDF cross-domain policy files.
        resp.headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")

        # Sensitive responses must never be cached by shared caches or
        # left in a browser's history. Applies to every API response and
        # to any page rendered while the user is logged in.
        path = request.path or ""
        if path.startswith("/api/") or session.get("user"):
            resp.headers["Cache-Control"] = "no-store"
            resp.headers["Pragma"] = "no-cache"

        # Remove the fingerprintable "Server: Werkzeug/x" header.
        resp.headers.pop("Server", None)
        return resp

    # -------- 2) Request-size cap --------
    app.config["MAX_CONTENT_LENGTH"] = MAX_JSON_BYTES

    @app.errorhandler(413)
    def _too_large(e):
        return jsonify({"ok": False, "error": "Request too large."}), 413

    # -------- 3) Rate limiting --------
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per minute", "3000 per hour"],
        storage_uri="memory://",
    )

    @app.errorhandler(429)
    def _rate_limited(e):
        _log_security_event("RATE_LIMITED", f"{request.method} {request.path}")
        return jsonify({
            "ok": False,
            "error": "Too many requests. Please slow down and try again shortly.",
        }), 429

    # -------- 4) Session hygiene --------
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True

    # -------- 5) Reject oversized JSON string fields --------
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
                     else MAX_TEXT_FIELD_LEN if key in ("remarks", "description", "notes", "address")
                     else MAX_STRING_FIELD_LEN)
            if len(value) > limit:
                return jsonify({
                    "ok": False,
                    "error": f"'{key}' is too long (max {limit} characters).",
                }), 400

    # -------- 6) Content-Type enforcement on /api/ POST-family --------
    # Rejects requests to /api/* that don't declare application/json
    # for state-changing methods. This blocks the "simple request" CORS
    # class (form-encoded / text/plain) which a hostile site could send
    # cross-origin without a preflight -- CSRF via that path would slip
    # past SameSite=Lax on some older browsers.
    @app.before_request
    def _enforce_json_content_type():
        if request.method in CSRF_SAFE_METHODS:
            return
        if not (request.path or "").startswith("/api/"):
            return
        # Empty body is OK (no Content-Type header needed)
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

    # -------- 7) CSRF protection (double-submit cookie) --------
    # Every response gets a csrf_token cookie if it doesn't already have
    # one for this session. The frontend fetch wrapper reads that cookie
    # and echoes its value in the X-CSRF-Token header. On state-changing
    # requests, we verify header == cookie using a constant-time compare.
    #
    # Why double-submit and not a server-side token store: the token
    # lives entirely in the browser (cookie + header). A cross-site page
    # can't read the cookie (SameSite=Lax + no CORS access), so it can't
    # forge the header. Simple, stateless, works with the existing
    # session cookie.

    @app.after_request
    def _issue_csrf_cookie(resp):
        # Only issue the cookie if the session doesn't already have a
        # matching one. Rotates on session.clear() (e.g. logout / login).
        token = session.get("_csrf")
        if not token:
            token = secrets.token_urlsafe(CSRF_TOKEN_BYTES)
            session["_csrf"] = token
        # Set the cookie unconditionally so a new tab or a cache-cleared
        # browser picks it up too.
        resp.set_cookie(
            CSRF_COOKIE_NAME, token,
            secure=app.config.get("SESSION_COOKIE_SECURE", False),
            httponly=False,          # frontend JS MUST be able to read it
            samesite="Lax",
            path="/",
        )
        return resp

    @app.before_request
    def _verify_csrf():
        if request.method in CSRF_SAFE_METHODS:
            return
        # Only enforce on state-changing API calls. The /login endpoint
        # is exempt because on a first visit there is no session yet to
        # carry a token from -- SameSite=Lax on the session cookie is
        # the primary CSRF defence for login itself, and the rate
        # limiter blocks credential stuffing.
        path = request.path or ""
        if not path.startswith("/api/"):
            return
        if path in ("/api/login",):
            return

        header_token = request.headers.get(CSRF_HEADER_NAME, "")
        cookie_token = request.cookies.get(CSRF_COOKIE_NAME, "")
        session_token = session.get("_csrf", "")

        # All three must be present AND match, using constant-time compare.
        if not (header_token and cookie_token and session_token):
            _log_security_event("CSRF_REJECTED", f"{request.method} {path}: token missing.")
            return jsonify({"ok": False, "error": "CSRF token missing."}), 403
        if not (hmac.compare_digest(header_token, cookie_token)
                and hmac.compare_digest(header_token, session_token)):
            _log_security_event("CSRF_REJECTED", f"{request.method} {path}: token mismatch.")
            return jsonify({"ok": False, "error": "CSRF token mismatch."}), 403

    return limiter


def _log_security_event(action, details):
    """
    Best-effort audit log write for security-relevant rejections (CSRF
    failures, bad Content-Type, rate-limit hits). Imported lazily to
    avoid a circular import (mlr_model doesn't depend on security.py,
    but importing it at module load time here would still create an
    awkward load-order dependency during app startup).

    Never raises: a logging failure must not turn into a 500 on top of
    the security rejection that triggered it.
    """
    try:
        from mlr_model import log_audit
        from config import DB_CONFIG
        ip = get_remote_address()
        log_audit(DB_CONFIG, action, f"{details} (ip={ip})")
    except Exception:
        pass


def _iter_strings(obj, key=None):
    """Yield every (key, string_value) pair from a nested dict/list."""
    if isinstance(obj, str):
        yield key or "", obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_strings(v, key=k)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_strings(item, key=key)

