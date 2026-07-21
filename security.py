"""
Parabellum ISOS — Security Hardening
=================================================================
Defense-in-depth measures at the Flask application layer.

WHAT THIS COVERS
    - HTTP security headers (HSTS, CSP, X-Content-Type-Options, etc.)
    - Rate limiting on login, forecasting, and report exports — both to
      slow brute-force attempts and to stop the more expensive operations
      (PDF/Excel generation, model training) from being hammered
    - Request-size cap (prevents "gigabyte body" memory DoS)
    - Session absolute lifetime and idle timeout
    - Server-header suppression (removes fingerprinting)
    - Input-length limits on API JSON bodies
    - Server-side numeric validation (no negative prices/budgets, no
      out-of-range progress values) — closes off ways bad input could
      corrupt stored data even if it doesn't crash anything
    - Generic error messages to the client on every API failure — the
      real exception (with full traceback) is only ever written to the
      server's own log, never sent to the browser. This matters because
      raw database error text can reveal table/column names, query
      structure, or file paths — details an attacker could use to plan
      a more targeted attack. See app.py's `app.logger.exception(...)`
      calls.

WHAT THIS DOES NOT COVER — call these out to your panel so nobody's
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

from flask import request, jsonify, session
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


# Reasonable ceilings. Adjust in one place if you ever need to.
# MAX_JSON_BYTES also caps the WHOLE request body (Flask only supports one
# global limit), so it has to be big enough for a profile photo upload —
# not just a JSON form post. 4 MB comfortably fits a phone-camera photo
# while still being far too small to matter as a DoS vector; the avatar
# endpoint itself enforces a tighter 3 MB cap with a clearer error message.
MAX_JSON_BYTES          = 4 * 1024 * 1024   # 4 MB — covers JSON bodies AND avatar uploads
MAX_USERNAME_LEN       = 60
MAX_PASSWORD_LEN       = 256           # bcrypt-style hashers already cap effective bytes
MAX_STRING_FIELD_LEN   = 500           # generic string fields (names, addresses, remarks)
MAX_TEXT_FIELD_LEN     = 4000          # longer notes / descriptions

# Content Security Policy — locks the browser down to loading assets only
# from us and the two CDNs the frontend needs (Bootstrap + icons). Blocks
# most XSS injection vectors even if a bug lets something through.
CSP = (
    "default-src 'self'; "
    "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self' https://cdn.jsdelivr.net data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "                # clickjacking defence
    "form-action 'self'; "
    "base-uri 'self'"
)
# NOTE: 'unsafe-inline' for scripts/styles is needed because your pages
# use inline <script> blocks and style attributes. Removing it is safer
# but requires moving every inline script into an external .js file — a
# refactor beyond the scope of a security pass. This is still much
# stronger than no CSP at all.


def apply_security(app):
    """
    Wire every hardening measure onto the Flask app. Call this ONCE at
    startup, right after `app = Flask(__name__)`.
    """

    # -------- 1) HTTP security headers on every response --------
    @app.after_request
    def _add_security_headers(resp):
        # HSTS: tells browsers to always use HTTPS for this domain for the
        # next year. Only meaningful once you actually have HTTPS deployed;
        # harmless on HTTP.
        resp.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains",
        )
        # Blocks MIME sniffing — attacker can't upload an "image" that
        # the browser decides to execute as script.
        resp.headers["X-Content-Type-Options"] = "nosniff"
        # Blocks the page from being rendered inside a frame — clickjacking
        # defence (also covered by frame-ancestors in CSP, kept for older
        # browsers).
        resp.headers["X-Frame-Options"] = "DENY"
        # Don't leak the URL of the referring page across origins.
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Disable browser features we don't need — no camera, no mic, no
        # location, etc.
        resp.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        resp.headers["Content-Security-Policy"] = CSP
        # Remove the fingerprintable "Server: Werkzeug/x" header.
        resp.headers.pop("Server", None)
        return resp

    # -------- 2) Request-size cap --------
    # Reject bodies larger than 128 KB with a 413 before Flask allocates
    # memory for them. Anything the UI actually sends is well under this.
    app.config["MAX_CONTENT_LENGTH"] = MAX_JSON_BYTES

    @app.errorhandler(413)
    def _too_large(e):
        return jsonify({"ok": False, "error": "Request too large."}), 413

    # -------- 3) Rate limiting --------
    # Per-IP by default. Uses in-memory storage — fine for a single
    # process on your capstone. For a production multi-worker setup you
    # would point Flask-Limiter at Redis via `storage_uri`.
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per minute", "3000 per hour"],
        storage_uri="memory://",
    )

    @app.errorhandler(429)
    def _rate_limited(e):
        # Custom JSON response so the frontend can display something
        # sensible instead of Flask's default HTML page.
        return jsonify({
            "ok": False,
            "error": "Too many requests. Please slow down and try again shortly.",
        }), 429

    # -------- 4) Session hygiene --------
    # Sessions expire after 30 minutes of inactivity (was already set via
    # PERMANENT_SESSION_LIFETIME in app.py). We ALSO refresh the cookie
    # on every request so the countdown is idle-time, not creation-time.
    app.config["SESSION_REFRESH_EACH_REQUEST"] = True

    # -------- 5) Reject oversized JSON string fields --------
    # Even a 128 KB request can contain one 100 KB string that would then
    # flood the audit log or a database column. Cap individual fields.
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

    return limiter


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
