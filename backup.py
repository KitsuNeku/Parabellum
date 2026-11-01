import re
from datetime import datetime, timezone

from psycopg2.extras import RealDictCursor

from db import connect_db

BACKUP_TABLES = [
    "company_settings", "users", "suppliers", "materials", "employees", "customers", "projects",
    "transactions", "stock_movements", "delivery_attempts", "back_orders", "chat_messages", "monthly_demand",
    "monthly_weather", "forecast_results", "model_metrics", "forecast_runs", "support_tickets", "support_messages", "audit_logs",
]


def generate_sql_backup(db_config):
    conn = connect_db(db_config)
    try:
        lines = [
            "-- =================================================================",
            "-- Parabellum ISOS -- Database Backup",
            f"-- Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}Z",
            "-- ",
            "-- RESTORE: run schema.sql on an EMPTY database first (it creates",
            "-- the tables), then run this file to reload the data. Tables are",
            "-- ordered here so foreign keys are always satisfied top-to-bottom.",
            "-- =================================================================",
            "",
            "BEGIN;",
            "",
        ]
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            for table in BACKUP_TABLES:
                cur.execute(f"SELECT * FROM {table} ORDER BY 1;")
                rows = cur.fetchall()
                lines.append(f"-- ---- {table} ({len(rows)} row{'s' if len(rows) != 1 else ''}) ----")
                if not rows:
                    lines.append("-- (no rows)")
                    lines.append("")
                    continue
                columns = list(rows[0].keys())
                col_list = ", ".join(columns)
                for row in rows:
                    values = tuple(row[c] for c in columns)
                    stmt = cur.mogrify(
                        f"INSERT INTO {table} ({col_list}) VALUES %s;", (values,)
                    )
                    lines.append(stmt.decode("utf-8"))
                lines.append("")
        lines.append("COMMIT;")
        lines.append("")
        return "\n".join(lines)
    finally:
        conn.close()


RESTORE_PK_MAP = {
    "users": "user_id",
    "materials": "material_id",
    "customers": "customer_id",
    "suppliers": "supplier_id",
    "projects": "project_id",
    "transactions": "transaction_id",
    "stock_movements": "movement_id",
    "delivery_attempts": "attempt_id",
    "back_orders": "back_order_id",
    "chat_messages": "message_id",
    "monthly_demand": "id",
    "monthly_weather": "id",
    "forecast_results": "forecast_id",
    "model_metrics": "metric_id",
    "forecast_runs": "run_id",
    "support_tickets": "ticket_id",
    "support_messages": "message_id",
    "employees": "employee_id",
    "audit_logs": "log_id",
}


def restore_sql_backup(db_config, sql_text):
    if not sql_text or "INSERT INTO" not in sql_text.upper():
        raise ValueError("This file doesn't look like a Parabellum backup -- no data was found inside it.")

    cleaned = re.sub(r"(?im)^\s*(BEGIN|COMMIT)\s*;\s*$", "", sql_text)

    conn = connect_db(db_config)
    try:
        with conn.cursor() as cur:
            table_list = ", ".join(BACKUP_TABLES)
            cur.execute(f"TRUNCATE TABLE {table_list} CASCADE;")

            cur.execute(cleaned)

            for table in BACKUP_TABLES:
                pk = RESTORE_PK_MAP.get(table)
                if not pk:
                    continue
                cur.execute(f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table}', '{pk}'),
                        COALESCE((SELECT MAX({pk}) FROM {table}), 1),
                        (SELECT MAX({pk}) FROM {table}) IS NOT NULL
                    );
                """)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
