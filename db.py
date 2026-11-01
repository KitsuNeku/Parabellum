import psycopg2
from psycopg2.extras import RealDictCursor, execute_values

def connect_db(db_config):
    return psycopg2.connect(**db_config)


def execute_query(db_config, query, params=None, fetch=False):
    conn = connect_db(db_config)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            result = cur.fetchall() if fetch else None
        conn.commit()
        return result
    finally:
        conn.close()


def log_audit(db_config, action, details, username="system"):
    try:
        execute_query(
            db_config,
            "INSERT INTO audit_logs (username, action, details) VALUES (%s, %s, %s);",
            (username, action, details),
        )
    except Exception:
        pass


def bulk_insert(db_config, sql, rows, page_size=500):
    if not rows:
        return
    conn = connect_db(db_config)
    try:
        with conn.cursor() as cur:
            execute_values(cur, sql, rows, page_size=page_size)
        conn.commit()
    finally:
        conn.close()


COMPANY_DEFAULTS = {
    "company_name": "Parabellum Steel & Iron Works",
    "tin": "", "email": "", "phone": "", "address": "",
    "currency": "PHP", "vat_rate": 12.0,
}


def get_company_settings(db_config):
    try:
        rows = execute_query(db_config, """
            SELECT company_name, tin, email, phone, address, currency, vat_rate
            FROM company_settings WHERE id = 1;
        """, fetch=True)
    except Exception:
        rows = None
    if not rows:
        return dict(COMPANY_DEFAULTS)
    r = rows[0]
    return {
        "company_name": r["company_name"] or COMPANY_DEFAULTS["company_name"],
        "tin": r["tin"] or "", "email": r["email"] or "", "phone": r["phone"] or "",
        "address": r["address"] or "", "currency": r["currency"] or "PHP",
        "vat_rate": float(r["vat_rate"]) if r["vat_rate"] is not None else 12.0,
    }


SESSION_TIMEOUTS = (15, 30, 60, 120)
_security_cache = {"at": 0.0, "data": None}


def get_security_settings(db_config, fresh=False):
    import time
    if not fresh and _security_cache["data"] and time.time() - _security_cache["at"] < 30:
        return _security_cache["data"]
    data = {"session_timeout_min": 30, "require_2fa_admins": False, "login_alerts": False}
    try:
        rows = execute_query(db_config, """
            SELECT session_timeout_min, require_2fa_admins, login_alerts
            FROM company_settings WHERE id = 1;
        """, fetch=True)
        if rows:
            r = rows[0]
            timeout = int(r["session_timeout_min"] or 30)
            data = {
                "session_timeout_min": timeout if timeout in SESSION_TIMEOUTS else 30,
                "require_2fa_admins": bool(r["require_2fa_admins"]),
                "login_alerts": bool(r["login_alerts"]),
            }
    except Exception:
        pass
    _security_cache.update(at=time.time(), data=data)
    return data
