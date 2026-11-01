import psycopg2
from werkzeug.security import generate_password_hash
from config import DB_CONFIG

DEMO_USERS = [
    ("admin",      "Admin!2026",      "Admin User",        "System Administrator",
     "admin@parabellumsteel.com.ph", "IT / Management"),
    ("inventory1", "Inventory!2026",  "Inventory Clerk",    "Inventory Personnel",
     "inventory@parabellumsteel.com.ph", "Warehouse"),
    ("ops1",       "Operations!2026", "Operations Staff",   "Operations Personnel",
     "ops@parabellumsteel.com.ph", "Operations"),
    ("manager1",   "Manager!2026",    "Management Owner",   "Management/Owner",
     "manager@parabellumsteel.com.ph", "Executive"),
    ("jramos",     "Ramos!2026warehouse",   "John Erick Ramos",  "Inventory Personnel",
     "jramos@parabellumsteel.com.ph", "Warehouse"),
    ("rbautista",  "Bautista!2026warehouse", "Ronnel Bautista",  "Inventory Personnel",
     "rbautista@parabellumsteel.com.ph", "Warehouse"),
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
