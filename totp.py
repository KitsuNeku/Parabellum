import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

ISSUER = "Parabellum ISOS"
STEP = 30
DIGITS = 6


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _code_at(secret, counter):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(value % (10 ** DIGITS)).zfill(DIGITS)


def current_step(now=None):
    return int((now or time.time()) // STEP)


def verify(secret, code, last_step=None, window=1, now=None):
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    if not secret or len(code) != DIGITS:
        return None
    step = current_step(now)
    for offset in range(-window, window + 1):
        candidate = step + offset
        if last_step is not None and candidate <= last_step:
            continue
        if hmac.compare_digest(_code_at(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(username, secret):
    label = quote(f"{ISSUER}:{username}")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={DIGITS}&period={STEP}"
