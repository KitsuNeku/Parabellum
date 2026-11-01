import json

from db import execute_query

ACCENTS = {
    "red":    ("#b11217", "177, 18, 23",   "#8a1214", "#6e0f11"),
    "blue":   ("#1d4ed8", "29, 78, 216",   "#1e40af", "#1e3a8a"),
    "green":  ("#047857", "4, 120, 87",    "#065f46", "#064e3b"),
    "purple": ("#7c3aed", "124, 58, 237",  "#6d28d9", "#5b21b6"),
    "slate":  ("#0f172a", "15, 23, 42",    "#1e293b", "#020617"),
}

DEFAULTS = {
    "accent": "red",
    "dark": False,
    "compact": True,
    "sidebarCollapsible": True,
    "notify": {"lowStock": True, "forecast": True, "transactions": True, "emailDigest": False},
}


def normalize(raw):
    raw = raw if isinstance(raw, dict) else {}
    out = json.loads(json.dumps(DEFAULTS))
    if raw.get("accent") in ACCENTS:
        out["accent"] = raw["accent"]
    for key in ("dark", "compact", "sidebarCollapsible"):
        if isinstance(raw.get(key), bool):
            out[key] = raw[key]
    notify = raw.get("notify") if isinstance(raw.get("notify"), dict) else {}
    for key in out["notify"]:
        if isinstance(notify.get(key), bool):
            out["notify"][key] = notify[key]
    return out


def merge(current, changes):
    base = normalize(current)
    changes = changes if isinstance(changes, dict) else {}
    combined = dict(base)
    for key, value in changes.items():
        if key == "notify" and isinstance(value, dict):
            combined["notify"] = {**base["notify"], **value}
        else:
            combined[key] = value
    return normalize(combined)


def load(db_config, user_id):
    if not user_id:
        return normalize({})
    try:
        rows = execute_query(db_config, "SELECT preferences FROM users WHERE user_id = %s;",
                             (user_id,), fetch=True)
    except Exception:
        return normalize({})
    raw = rows[0]["preferences"] if rows else {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raw = {}
    return normalize(raw)


def save(db_config, user_id, prefs):
    execute_query(db_config, "UPDATE users SET preferences = %s::jsonb WHERE user_id = %s;",
                  (json.dumps(prefs), user_id))
