import sys

import psycopg2

from config import DB_CONFIG


def run(path):
    with open(path, encoding="utf-8") as f:
        sql = f.read()
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    for p in sys.argv[1:]:
        run(p)
        print(f"Migration OK: {p}")
