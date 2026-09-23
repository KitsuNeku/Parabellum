# Parabellum ISOS — Security Posture

This is the honest, plain-language inventory of what the system defends
against, how, and — just as important — what it does NOT defend against
and why that's acceptable for its deployment context.

## Threat model

Deployment context: a small-business inventory + forecasting web app,
running on Flask, backed by managed Postgres (Supabase), reachable
over the public internet by a handful of named users (all logged in).
No public / anonymous write surface except the login page.

The realistic threats we actually design against are:

1. **SQL injection** — an attacker submitting crafted input that a
   poorly-written query concatenates into a database command.
2. **Cross-site scripting (XSS)** — malicious HTML/JS getting stored
   in the DB and rendered into another user's browser.
3. **Cross-site request forgery (CSRF)** — a hostile page tricking
   the browser into calling our API using the user's session.
4. **Session hijacking / fixation** — stealing or pre-planting a
   session cookie to impersonate a user.
5. **Brute-force / credential stuffing** — automated password guessing.
6. **Application-layer denial of service** — a single actor
   hammering expensive endpoints (report generation, model training).
7. **Information disclosure** — error pages leaking table names, file
   paths, stack traces, or fingerprintable server headers.
8. **Malicious file upload** — using the avatar upload to store
   payloads or exhaust disk.

We do NOT try to defend against:

* **Network-layer DDoS** — a real botnet requires a real DDoS
  scrubber (Cloudflare, AWS Shield). Application-layer rate limits
  slow one abusive IP; they cannot stop 10,000 IPs.
* **Compromised admin accounts** — anyone with admin credentials can
  do anything the app allows. Password strength + lockout + audit
  logs are the mitigation, not a wall.
* **Compromised host / OS** — that's the hosting provider's layer.
* **Physical access to the server or DB** — same.

## What's in the codebase, threat by threat

### 1. SQL injection

* **Every** database call goes through `mlr_model.execute_query`
  (or `_bulk_insert` / `execute_values`), and every query uses
  parameterized placeholders (`%s`) with a separate params tuple.
  psycopg2 handles the escaping. No string formatting into SQL exists
  anywhere in the codebase.
* **How to verify**: `grep -rn "execute" *.py` — every hit passes the
  values as a tuple, never string-interpolated into the query.

### 2. XSS

* **Jinja templates** auto-escape variables. No `|safe` filter is
  used anywhere.
* **Content Security Policy** (`security.py` → `CSP`) restricts
  script/style/font/img sources to self + one CDN, blocks
  `frame-ancestors` (clickjacking), and locks `base-uri` and
  `form-action` to self.
* **`X-Content-Type-Options: nosniff`** blocks MIME sniffing so an
  uploaded file the server labels as `image/png` can't be executed as
  script by the browser.
* **Frontend `esc()` helper** in `static/js/app.js` HTML-escapes any
  DB-derived string before it goes into `innerHTML` /
  `insertAdjacentHTML`. Applied to customer, project, and material
  names on all dropdowns and tables where they appear.

### 3. CSRF

* **Session cookie** is `HttpOnly` + `SameSite=Lax` + `Secure` when
  `SESSION_COOKIE_SECURE=1` is set. `SameSite=Lax` alone blocks
  cross-site POST from a `<form>` submission on modern browsers.
* **Double-submit token** (defense-in-depth on top of `SameSite`).
  Server sets a `csrf_token` cookie (readable by JS, not HttpOnly);
  frontend fetch wrapper reads it and echoes it in an `X-CSRF-Token`
  header on every state-changing `/api/*` call; server rejects
  mismatched or missing tokens with 403. Verification uses
  `hmac.compare_digest` (constant-time).
* **Content-Type enforcement** on state-changing `/api/*` requests —
  anything other than `application/json` returns 415 before touching
  business logic. Closes off the "simple request" CORS class that
  older browsers might allow cross-origin without a preflight.

### 4. Session security

* **Server-side signed session** (Flask default, keyed by
  `SECRET_KEY`).
* **`session.clear()` on login** (`app.py` login endpoint) — the
  session identity is regenerated on every authentication event,
  preventing session fixation. This also rotates the CSRF token
  (§3), since `_issue_csrf_cookie` mints a fresh one whenever
  `session["_csrf"]` is absent.
* **`SESSION_REFRESH_EACH_REQUEST=True`** — the 30-minute session
  lifetime is an IDLE timeout, not an absolute one.
* **Absolute session lifetime — 12 hours** (`auth.py` →
  `ABSOLUTE_SESSION_HOURS`), independent of activity. A session
  used continuously every few minutes still forces re-login after
  12 hours. This caps how long a stolen or left-open session cookie
  stays useful to an attacker, regardless of the idle timeout.
* **`SECRET_KEY`** defaults to a fresh `secrets.token_hex(32)` if
  the env var is unset. Set it once in production so sessions
  survive restarts.

### 4a. Reverse proxy / real client IP (ProxyFix)

* **Off by default.** If deployed directly (no reverse proxy), every
  request's IP is exactly what it appears to be — no change needed.
* **Opt-in via `TRUST_PROXY=1`** (`app.py`) for deployments behind
  nginx, Caddy, Cloudflare, or a hosting platform's load balancer.
  Without this, every request looks like it came from the proxy's
  own IP, which silently breaks per-IP rate limiting (all users
  share one limit) and the IP recorded in `audit_logs` (useless for
  investigating an incident).
* **Why opt-in and not automatic**: trusting `X-Forwarded-For` when
  there is NO real proxy in front lets any client set that header
  themselves and spoof an arbitrary IP — trivially bypassing rate
  limits and forging the audit trail. Only set this once you've
  confirmed a reverse proxy is the sole thing that can reach the
  Flask process directly.

### 5. Brute-force / credential stuffing

* **Account lockout**: 5 failed attempts → 15-minute cooldown
  (`auth.py` → `MAX_FAILED_ATTEMPTS` / `LOCKOUT_MINUTES`).
* **Password minimum length**: 12 characters, enforced in
  `hash_password` via `validate_password_strength`. Also rejects
  whitespace-only and near-single-character passwords.
* **Passwords hashed** with werkzeug's `generate_password_hash`
  (PBKDF2-SHA256 with per-password salt). No plaintext passwords are
  ever stored or logged.
* **Rate limiting** on the login endpoint (per-IP) via
  `Flask-Limiter`.
* **Timing-safe unknown-username handling**: `verify_login` runs a
  real (but pointless) password-hash comparison against a fixed
  dummy hash even when the username doesn't exist
  (`auth._DUMMY_HASH`), so an unknown username takes the same amount
  of time to reject as a wrong password for a real one. Without
  this, the unknown-username path returned immediately after one
  fast query while the known-username path ran a ~50-100ms PBKDF2
  check — a measurable timing side-channel an attacker could use to
  enumerate valid usernames even though the error TEXT was already
  identical in both cases.
* **Known tradeoff, not fixed**: the "account disabled" and
  "account locked, try again in N minutes" messages ARE
  distinguishable from "invalid username or password" — so a
  determined attacker who already suspects a username exists can
  confirm it by triggering a lockout and reading the message. This
  is a deliberate usability choice (a legitimate locked-out user
  needs to know why), not an oversight. If stricter anti-enumeration
  matters more than that usability for your deployment, collapse all
  three messages to the same generic text.

### 6. Application-layer DoS

* **Per-IP rate limits** — default 200/min and 3000/hour on every
  route; tighter limits on the expensive ones:
  * `/api/forecast` — 6/minute (each call retrains the model)
  * `/api/weather/sync` — 6/hour (external HTTPS to Open-Meteo)
* **Request body cap** — 4 MB (`MAX_CONTENT_LENGTH`). Anything
  larger returns 413 before Flask allocates memory.
* **String-field length cap** — server-side check on every JSON
  request; individual fields are limited to 60 chars (username),
  256 (password), 500 (generic), or 4000 (long-form notes).

### 7. Information disclosure

* **Generic error messages** — every `/api/*` endpoint that catches an
  exception returns a fixed user-facing message; the actual traceback
  and error text goes only to the server log via
  `app.logger.exception`. The client never sees database column
  names, file paths, or stack traces.
* **Server header removed** — no `Server: Werkzeug/...` fingerprint.
* **`Cache-Control: no-store`** on all `/api/*` responses and on any
  page rendered while the user is logged in. Sensitive data isn't
  cached by shared browsers/proxies.
* **`Referrer-Policy: strict-origin-when-cross-origin`** — clicking
  a link from a logged-in page doesn't send the full URL (which could
  contain identifiers) to the destination site.
* **`Cross-Origin-Opener-Policy: same-origin`**,
  **`Cross-Origin-Resource-Policy: same-origin`**,
  **`X-Permitted-Cross-Domain-Policies: none`** — isolation from
  hostile pages.
* **`FLASK_DEBUG` defaults to OFF** (see `config.py`). Debug mode
  exposes an interactive Python console on error pages, so it must
  never be enabled where the app is reachable by anyone other than
  the developer. Explicitly opt in with `FLASK_DEBUG=1` for local
  development only.

### 8. File upload

* Avatar upload writes only into a fixed directory, validates the
  Content-Type against an allowlist, and enforces a 3 MB per-file
  cap on top of the app-wide 4 MB body cap. Filenames go through
  `werkzeug.utils.secure_filename`.
* **Magic-byte validation**: the extension check alone only looks
  at the filename the client CLAIMS — nothing stops uploading
  arbitrary content (an HTML/JS payload, a script) with a `.png`
  name. `_content_matches_extension` reads the file's actual first
  bytes and checks them against the real signature for PNG, JPEG,
  GIF, and WEBP (WEBP additionally verified via its RIFF container's
  `WEBP` fourcc, not just the generic RIFF prefix). A mismatch is
  rejected AND logged to the audit trail as `AVATAR_REJECTED`.

### 9. Extended audit logging

Beyond login events (already covered), these security-relevant
rejections are now also written to `audit_logs` so an investigation
after an incident has something to look at instead of only the
generic 403/415/429 the client saw:

* `CSRF_REJECTED` — missing or mismatched CSRF token, with the
  method, path, and requesting IP.
* `CONTENT_TYPE_REJECTED` — a state-changing `/api/*` call with the
  wrong Content-Type.
* `RATE_LIMITED` — any request that tripped a rate limit.
* `AVATAR_REJECTED` — an upload whose content didn't match its
  claimed extension.

These are best-effort (`_log_security_event` swallows its own
failures) so a logging hiccup never turns into an unrelated 500 on
top of the rejection that triggered it.

## Deployment checklist

Before pointing real traffic at this:

- [ ] Set `SECRET_KEY` env var to a fixed random value
      (`python -c "import secrets; print(secrets.token_hex(32))"`).
- [ ] Set `FLASK_DEBUG=0` (or don't set it — that's the default now).
- [ ] Set `SESSION_COOKIE_SECURE=1` once you're serving over HTTPS.
- [ ] Set `TRUST_PROXY=1` ONLY if you are deploying behind a real
      reverse proxy (nginx/Caddy/Cloudflare/hosting load balancer).
      Leave unset for a direct deployment — setting it without an
      actual proxy in front lets clients spoof their own IP.
- [ ] Put HTTPS in front of the app (Let's Encrypt + nginx/Caddy, or
      a hosting platform that terminates TLS).
- [ ] Put **Cloudflare** (free tier) or your host's DDoS mitigation
      in front for real DoS protection. Application-level rate limits
      are not a DDoS defense.
- [ ] Rotate database credentials from the seed defaults. `config.py`
      reads from env vars — set them at deploy time, never commit the
      values.
- [ ] Turn on Supabase's backup schedule if it isn't already.

## What to say if a panel asks

> *"Standard web-app defenses at the application layer: parameterized
> SQL with psycopg2 (blocks injection), Jinja auto-escaping plus a
> Content Security Policy and per-interpolation escape helper (blocks
> XSS), SameSite session cookies plus double-submit CSRF tokens (blocks
> CSRF), session regeneration on login (blocks fixation), account
> lockout with rate limiting (blocks brute force), tight rate limits
> and body caps on expensive endpoints (mitigates application-layer
> DoS), and generic error messages with server-side-only logging
> (blocks information disclosure). What we don't try to defend
> against — network-layer DDoS, compromised admin credentials, host
> compromise — needs infrastructure the app can't provide by itself:
> Cloudflare, MFA, or the hosting provider."*
