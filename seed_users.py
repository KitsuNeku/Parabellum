"""
Seed demo user accounts for Parabellum ISOS.
=================================================================
Run ONCE, after schema.sql:

    python seed_users.py

Creates one account per role so you can demonstrate role-based access
control at your defense. Passwords are hashed with werkzeug's
generate_password_hash before they ever touch the database - the
database never stores or sees the plain-text password.

IMPORTANT: these are DEMO credentials for development and your
defense rehearsal. Change them (or create real accounts and disable
these) before any real deployment.
"""

import psycopg2
from werkzeug.security import generate_password_hash
from config import DB_CONFIG

# username, password, full name, role, email, department
# Role strings MUST exactly match ROLE_PERMISSIONS in data.js / auth.py.
DEMO_USERS = [
    ("admin",      "Admin!2026",      "Admin User",        "System Administrator",
     "admin@parabellumsteel.com.ph", "IT / Management"),
    ("inventory1", "Inventory!2026",  "Inventory Clerk",    "Inventory Personnel",
     "inventory@parabellumsteel.com.ph", "Warehouse"),
    ("ops1",       "Operations!2026", "Operations Staff",   "Operations Personnel",
     "ops@parabellumsteel.com.ph", "Operations"),
    ("manager1",   "Manager!2026",    "Management Owner",   "Management/Owner",
     "manager@parabellumsteel.com.ph", "Executive"),
]


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    for username, password, full_name, role, email, dept in DEMO_USERS:
        cur.execute(
            """
            INSERT INTO users (username, password_hash, full_name, role, email, department)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                password_hash   = EXCLUDED.password_hash,
                full_name       = EXCLUDED.full_name,
                role            = EXCLUDED.role,
                email           = EXCLUDED.email,
                department      = EXCLUDED.department,
                is_active       = TRUE,
                failed_attempts = 0,
                locked_until    = NULL;
            """,
            (username, generate_password_hash(password), full_name, role, email, dept),
        )

    conn.commit()
    cur.close()
    conn.close()

    print("Demo accounts ready:\n")
    print(f"  {'USERNAME':14s} {'PASSWORD':18s} ROLE")
    for username, password, full_name, role, email, dept in DEMO_USERS:
        print(f"  {username:14s} {password:18s} {role}")
    print("\nThese are for development / defense rehearsal only.")
    print("Change or disable them before any real deployment.")


if __name__ == "__main__":
    main()
