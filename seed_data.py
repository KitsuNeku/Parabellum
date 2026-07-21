"""
Seed sample operational data for Parabellum ISOS.
=================================================================
Monthly forecasting needs YEARS of history, not days. This generates
30 months (Jan 2024 - Jun 2026) of materials, projects, transactions,
and stock movements so the MLR model has something real to learn from.

Run ONCE, after schema.sql:

    python seed_data.py

Demand here is generated from a genuine underlying relationship
(previous demand + project activity + business volume + seasonality
+ noise), which is how demand behaves in a real fabrication shop.
The model has to discover that relationship from the records — it is
not handed the answer.

NOTE: this is SAMPLE data for development and defense rehearsal.
Replace it with Parabellum's real historical records when available.
"""

import random
from datetime import date, timedelta

import numpy as np
import psycopg2
from config import DB_CONFIG

random.seed(42)

MATERIALS = [
    # code,     name,                        unit,     unit_cost, reorder, category, supplier, location
    ("STL-016", "Deformed Steel Bar 16mm",   "pcs",      285.00,  400, "Bars",   "SteelAsia",      "Warehouse A"),
    ("GIS-005", "GI Sheet Corrugated 0.5mm", "sheets",   640.00,   60, "Sheets", "Puyat Steel",    "Warehouse B"),
    ("MSP-006", "MS Plate 4x8 (6mm)",        "sheets",  2450.00,   40, "Plates", "Capitol Steel",  "Yard 1"),
    ("ANG-506", "Angle Bar 50x50x6mm",       "length",   520.00,  150, "Bars",   "Pag-asa Steel",  "Yard 1"),
    ("HBM-200", "H-Beam 200x200",            "pcs",     8900.00,   20, "Beams",  "Cathay Metal",   "Yard 2"),
    ("CPU-206", "C-Purlins 2x6 (1.6mm)",     "length",   410.00,  180, "Tubes & Pipes", "SteelAsia", "Warehouse A"),
    ("SQT-202", "Square Tube 2x2 (1.5mm)",   "length",   375.00,  160, "Tubes & Pipes", "Treasure Steelworks", "Warehouse B"),
    ("FLB-014", "Flat Bar 1x1/4",            "length",   190.00,  200, "Bars",   "Pag-asa Steel",  "Yard 1"),
]

# Baseline monthly appetite for each material, and how strongly each one
# responds to project activity.
PROFILE = {
    "STL-016": (150, 9.0), "GIS-005": (60, 4.5), "MSP-006": (45, 3.0),
    "ANG-506": (95, 6.0),  "HBM-200": (18, 2.2), "CPU-206": (120, 7.5),
    "SQT-202": (80, 5.0),  "FLB-014": (70, 4.0),
}

CUSTOMERS = [
    "Lipa Builders Corp.", "Batangas Steel Traders", "MJ Construction",
    "Southridge Devt.", "Calabarzon Fabricators", "Villa Rosa Homes",
    "Trinity Warehousing", "Prime Metal Works",
]

START = date(2024, 1, 1)
N_MONTHS = 30


def month_start(i):
    y, m = divmod(START.month - 1 + i, 12)
    return date(START.year + y, m + 1, 1)


def main():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    print("Clearing existing records…")
    cur.execute("""
        TRUNCATE monthly_demand, forecast_results, model_metrics,
                 stock_movements, transactions, projects, customers,
                 employees, materials, audit_logs
        RESTART IDENTITY CASCADE;
    """)

    # ---- Materials (D2) ----
    ids = {}
    for code, name, unit, cost, reorder, category, supplier, location in MATERIALS:
        cur.execute(
            """INSERT INTO materials
                 (material_code, material_name, unit, unit_cost,
                  current_stock, reorder_level, category, supplier, location)
               VALUES (%s, %s, %s, %s, 0, %s, %s, %s, %s) RETURNING material_id;""",
            (code, name, unit, cost, reorder, category, supplier, location),
        )
        ids[code] = cur.fetchone()[0]
    print(f"  {len(ids)} materials")

    # ---- Employees (commission computation reads this) ----
    # Codes must match the EMP-01..EMP-06 range projects.staff uses below.
    EMPLOYEES = [
        ("EMP-01", "Engr. Juan Dela Cruz", "Senior Sales Engineer", 5.0),
        ("EMP-02", "Engr. Maria Santos",   "Sales Engineer",        4.5),
        ("EMP-03", "Engr. Carlos Mendoza", "Project Engineer",      4.0),
        ("EMP-04", "Engr. Ana Lim",        "Sales Engineer",        4.5),
        ("EMP-05", "Engr. Pedro Reyes",    "Senior Sales Engineer", 5.0),
        ("EMP-06", "Engr. Grace Villanueva", "Project Engineer",    4.0),
    ]
    for code, name, role, rate in EMPLOYEES:
        cur.execute(
            """INSERT INTO employees (employee_code, name, role, commission_rate, status)
               VALUES (%s, %s, %s, %s, 'Active');""",
            (code, name, role, rate),
        )
    print(f"  {len(EMPLOYEES)} employees")

    # ---- Customers ----
    contacts = ["Ramon Aquino", "Liza Tan", "Jose Marquez", "Grace Lim",
                "Paolo Reyes", "Maria Santos", "Ben Cruz", "Ana Villar"]
    cust_ids = {}
    for idx, cname in enumerate(CUSTOMERS):
        code = f"CUS-{201 + idx}"
        cur.execute(
            """INSERT INTO customers
                 (customer_code, name, contact_person, phone, email, address, status)
               VALUES (%s, %s, %s, %s, %s, %s, 'Active') RETURNING customer_id;""",
            (code, cname, contacts[idx % len(contacts)],
             f"09{random.randint(10,99)}-{random.randint(100,999)}-{random.randint(1000,9999)}",
             f"orders@{cname.split()[0].lower()}.com.ph",
             random.choice(["Lipa City, Batangas", "Quezon City", "Pasig City",
                            "Makati City", "Batangas City"])),
        )
        cust_ids[cname] = cur.fetchone()[0]
    print(f"  {len(cust_ids)} customers")

    # ---- Projects: a growing shop, 2-7 running at any time ----
    project_ids = []
    priorities = ["High", "Medium", "Low"]
    for i in range(N_MONTHS):
        ms = month_start(i)
        # gentle growth over time + seasonal dip in the rainy months
        n_new = random.randint(1, 2) + (1 if i > 14 else 0)
        if ms.month in (7, 8, 9):
            n_new = max(1, n_new - 1)
        for _ in range(n_new):
            dur = random.randint(2, 6)
            start = ms + timedelta(days=random.randint(0, 27))

            # Jobs started near the end of the window are still running, so
            # they carry into the forecast month. A real shop always has work
            # in progress — and the forecast needs to know about it.
            still_running = (i + dur) >= N_MONTHS
            end = None if still_running else month_start(i + dur) + timedelta(days=20)
            cust_name = random.choice(CUSTOMERS)

            cur.execute(
                """INSERT INTO projects
                     (project_code, project_name, customer_name, customer_id,
                      start_date, end_date, status, budget, priority, progress, staff)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING project_id;""",
                (f"PRJ-{300 + len(project_ids) + 1}",
                 f"Fabrication Job {ms.year}-{ms.month:02d}-{random.randint(100,999)}",
                 cust_name, cust_ids[cust_name], start, end,
                 "Ongoing" if still_running else "Completed",
                 round(random.uniform(400_000, 3_500_000), 2),
                 random.choice(priorities),
                 100 if not still_running else random.randint(20, 85),
                 f"EMP-{random.randint(1, 6):02d}"),
            )
            project_ids.append((cur.fetchone()[0], start,
                                end or date(2099, 12, 31)))
    print(f"  {len(project_ids)} projects")

    # ---- Transactions: business volume, tracks project activity ----
    n_txn = 0
    for i in range(N_MONTHS):
        ms = month_start(i)
        me = month_start(i + 1) if i + 1 < N_MONTHS else ms + timedelta(days=30)
        live = [p for p in project_ids if p[1] <= me and p[2] >= ms]
        volume = len(live) * random.randint(3, 6) + random.randint(2, 8)
        for _ in range(volume):
            d = ms + timedelta(days=random.randint(0, (me - ms).days - 1))
            pid = random.choice(live)[0] if live else None
            cust_name = random.choice(CUSTOMERS)
            mat = random.choice(MATERIALS)  # (code, name, unit, cost, reorder, cat, sup, loc)
            q = random.randint(5, 120)
            price = round(mat[3] * random.uniform(1.15, 1.4), 2)  # markup over cost
            cur.execute(
                """INSERT INTO transactions
                     (project_id, customer_id, customer_name, txn_date, amount,
                      material_name, quantity, unit_price, payment_status, payment_method)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);""",
                (pid, cust_ids[cust_name], cust_name, d, round(q * price, 2),
                 mat[1], q, price,
                 random.choice(["Paid", "Paid", "Partial", "Pending"]),
                 random.choice(["Bank Transfer", "Check", "Cash", "On Account"])),
            )
            n_txn += 1
    print(f"  {n_txn} transactions")

    # ---- Stock movements: demand driven by a real relationship ----
    prev_demand = {c: PROFILE[c][0] for c, *_ in MATERIALS}
    stock = {c: PROFILE[c][0] * 3 for c, *_ in MATERIALS}
    n_mov = 0

    # Opening inventory MUST be recorded as a real movement. The forecasting
    # service derives the stock balance by replaying receipts and issuances,
    # so any stock that never appears as a receipt is invisible to it.
    for code, name, unit, cost, reorder, category, supplier, location in MATERIALS:
        cur.execute(
            """INSERT INTO stock_movements
                 (material_id, movement_type, quantity, movement_date, remarks)
               VALUES (%s, 'RECEIPT', %s, %s, %s);""",
            (ids[code], stock[code], START, "Opening inventory"),
        )
        n_mov += 1

    for i in range(N_MONTHS):
        ms = month_start(i)
        me = month_start(i + 1) if i + 1 < N_MONTHS else ms + timedelta(days=30)
        days = (me - ms).days

        live = [p for p in project_ids if p[1] <= me and p[2] >= ms]
        n_proj = len(live)
        txn_vol = n_proj * 4 + 5

        for code, name, unit, cost, reorder, category, supplier, location in MATERIALS:
            base, proj_beta = PROFILE[code]

            # The relationship the model must recover from the data:
            #   demand = momentum + project pull + business volume
            #            + seasonality - drag from sitting stock + noise
            seasonal = 1.0 + 0.16 * np.sin(2 * np.pi * (ms.month - 3) / 12)
            demand = (
                0.34 * prev_demand[code]
                + proj_beta * n_proj
                + 0.28 * txn_vol
                + 0.42 * base
                - 0.012 * stock[code]
            ) * seasonal
            demand *= random.uniform(0.88, 1.12)          # real-world noise
            demand = max(1, round(demand))

            # Restock to roughly one month of cover. A fabrication shop buys
            # per job — it does not sit on several months of steel — so stock
            # is drawn down close to the bone and genuinely needs reordering.
            desired_opening = demand * random.uniform(1.05, 1.7)
            receipt = max(0, round(desired_opening - stock[code]))
            if receipt > 0:
                cur.execute(
                    """INSERT INTO stock_movements
                         (material_id, movement_type, quantity, movement_date, remarks)
                       VALUES (%s, 'RECEIPT', %s, %s, %s);""",
                    (ids[code], receipt,
                     ms + timedelta(days=random.randint(0, 4)),
                     "Supplier delivery"),
                )
                stock[code] += receipt
                n_mov += 1

            # Issue the month's demand across several withdrawals.
            remaining = demand
            for _ in range(random.randint(3, 7)):
                if remaining <= 0:
                    break
                qty = max(1, round(remaining * random.uniform(0.15, 0.45)))
                qty = min(qty, remaining, stock[code])
                if qty <= 0:
                    break
                pid = random.choice(live)[0] if live else None
                cur.execute(
                    """INSERT INTO stock_movements
                         (material_id, movement_type, quantity, movement_date,
                          project_id, remarks)
                       VALUES (%s, 'ISSUANCE', %s, %s, %s, %s);""",
                    (ids[code], qty,
                     ms + timedelta(days=random.randint(1, days - 1)),
                     pid, "Project material usage"),
                )
                stock[code] -= qty
                remaining -= qty
                n_mov += 1

            prev_demand[code] = demand

    print(f"  {n_mov} stock movements")

    # Final live stock balance on the material master.
    for code in ids:
        cur.execute(
            "UPDATE materials SET current_stock = %s WHERE material_id = %s;",
            (stock[code], ids[code]),
        )

    conn.commit()
    cur.close()
    conn.close()
    print(f"\nSeeded {N_MONTHS} months (Jan 2024 - Jun 2026).")
    print("Next:  python app.py   ->  open /forecasting  ->  Run Forecast")


if __name__ == "__main__":
    main()
