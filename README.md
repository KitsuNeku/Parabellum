# Parabellum ISOS
### Inventory and Service Optimization System for Demand Forecasting and Operational Efficiency
Parabellum Steel and Iron Works — Capstone Project

A web-based system that centralizes inventory, customer/project transactions,
commissions, and reporting, with a machine-learning module that forecasts
**short-term monthly material demand** using Multiple Linear Regression.

---

## 1. What works right now

| Area | Status |
|------|--------|
| All 12 pages served through Flask | Working |
| Clean routes (`/dashboard`, `/inventory`, …) | Working |
| Database schema (all 7 DFD data stores) | Working |
| Monthly demand forecasting (real MLR) | Working |
| Model evaluation — MAE, RMSE, MAPE, R² (out-of-sample) | Working |
| Forecast + metrics saved to the database | Working |
| Audit logging of forecast runs | Working |
| Sample data generator (30 months) | Working |
| Login (verifies credentials on the server) | **Working** — hashed passwords, sessions, lockout, audit log |
| Role-based access control | **Working** — enforced on the server, not just the sidebar |
| Dashboard shows real database data | **Working** |
| Inventory: receipts, issuances, negative-stock guard, reorder flags | **Working** |
| Customers: add / edit / delete, live project & transaction counts | **Working** |
| Projects: add / edit / delete, linked to customers | **Working** |
| Transactions: create + list, auto-deducts inventory (Obj. 1.3) | **Working** |
| Reports: real PDF & Excel export, on-screen preview | **Working** |
| Commission computation from the database | **Not yet** — Commission Report uses sample data |

The **forecasting engine and authentication are complete**. The remaining
work is the standard CRUD backend.

---

## 2. Technology used (as actually built)

| Component | Technology |
|-----------|-----------|
| Frontend | HTML, CSS, JavaScript (Bootstrap 5 via CDN) |
| Backend / web server | **Python + Flask** |
| Database | **PostgreSQL** (managed with pgAdmin) |
| Forecasting | scikit-learn — Multiple Linear Regression |
| Data processing | pandas, NumPy |

> **Note for the documentation:** the ASIA paper's technology table lists
> PHP / Laravel + MySQL, with Flask only as a separate forecasting service.
> This implementation uses **Flask for the whole backend and PostgreSQL**
> instead — one language, one database, far less integration work. Update
> the technology-stack table and Appendix D in the paper to match, or a
> panelist will notice the difference between the document and the code.

---

## 3. Project structure

```
Parabellum/
├── app.py              Flask server: 12 page routes + forecast API
├── config.py           Database credentials + session secret key
├── auth.py             Login, sessions, role enforcement
├── mlr_model.py        Monthly-demand forecasting model
├── seed_data.py         Generates 30 months of sample operational data
├── seed_users.py        Creates demo user accounts (run once)
├── schema.sql          Database tables (run in pgAdmin)
├── requirements.txt    Python libraries
├── .gitignore          Keeps config.py (your password) out of GitHub
│
├── templates/          The 12 HTML pages (Flask renders these)
│   ├── index.html          public landing page
│   ├── login.html          sign-in screen
│   ├── dashboard.html
│   ├── inventory.html
│   ├── customers.html
│   ├── projects.html
│   ├── transactions.html
│   ├── commissions.html
│   ├── forecasting.html
│   ├── reports.html
│   ├── settings.html
│   └── profile.html
│
└── static/             Served automatically by Flask
    ├── css/styles.css
    ├── js/  (app.js, charts.js, data.js)
    └── assets/img/  (logo, favicon, background)
```

---

## 4. Setup and run

### Prerequisites
- Python 3.10 or newer
- PostgreSQL with pgAdmin (already installed and running)

### Step 1 — Install the Python libraries
From inside the `Parabellum` folder:
```
pip install -r requirements.txt
```

### Step 2 — Set your database credentials
Open `config.py` and change these to match your setup:
```python
"dbname":   "parabellum_db",   # your database name
"user":     "postgres",        # usually "postgres"
"password": "CHANGE_ME",       # the password you set when installing PostgreSQL
```
The `dbname` must be a database you have already created in pgAdmin.

### Step 3 — Create the tables
In pgAdmin: right-click your database → **Query Tool** → open `schema.sql`
→ Run (**F5**). This creates all the tables.

### Step 4 — Create demo accounts (run once)
```
python seed_users.py
```
This creates one account per role so you can demonstrate role-based access
control. It prints the demo usernames and passwords to your terminal.

### Step 5 — Load sample operational data (run once)
```
python seed_data.py
```
This fills the database with 30 months of realistic materials, projects,
transactions, and stock movements so the model has history to learn from.

### Step 6 — Start the system
```
python app.py
```
Open **http://127.0.0.1:5000** in your browser, sign in with one of the demo
accounts (shown by `seed_users.py`), then go to the **Forecasting** page and
click **Run Forecast**.

**Using it on your phone:** see `MOBILE.md` for step-by-step instructions.
The short version: run `python app.py` on your PC, find your PC's IP with
`ipconfig`, and browse to `http://<your-ip>:5000` on your phone (both
devices on the same Wi-Fi).

**Moving the database to Supabase:** see `SUPABASE.md` for step-by-step
instructions. This lets your whole team (and your defense panel) work
against the same live database instead of everyone's separate local copy.

---

## 5. Security

This matches Objective 2.1 ("user authentication and role-based access
control") and the ISO 25010 Security row in the documentation.

- **Passwords are hashed**, never stored or compared as plain text
  (`werkzeug.security`, which ships with Flask — no extra install needed).
- **Sessions are server-side**, signed, and `HttpOnly` (JavaScript cannot
  read the session cookie, so it can't be stolen through an XSS bug), with
  `SameSite=Lax` to block most cross-site request forgery attempts.
- **Role checks are enforced on the server** (`auth.py`), not only by
  hiding sidebar links in the browser. Calling a restricted API directly —
  bypassing the UI entirely — is still blocked with a `403`.
- **Repeated wrong passwords lock the account** for 15 minutes after 5
  failed attempts, which blocks simple password-guessing.
- **Every login attempt is written to `audit_logs`** (D7) — success,
  failure, and lockouts — matching Appendix B and the admin testing table.
- **Login errors are generic** ("Invalid username or password") whether
  the username doesn't exist or the password is wrong, so a bad actor can't
  use error messages to find out which usernames are valid.
- **Flask's debug mode is off unless you explicitly enable it** — debug
  mode exposes an interactive Python console on error pages, which is a
  serious risk on anything reachable by more than just your own machine.

**What's intentionally out of scope for a class capstone**, so nobody is
surprised later: this app is not served over HTTPS (fine for local/LAN
demoing; add a reverse proxy with TLS before any real deployment), and the
login lockout counter resets if you restart the Flask process, since it's
tracked per account in the database rather than needing extra infrastructure.

---

## 6. How the forecasting works

The model predicts **next month's demand for every material** and follows the
process in the Data Flow Diagram:

1. **Aggregate** raw stock movements into a monthly table (DFD 3.2 → D4).
   Material *issuances* are treated as demand.
2. **Preprocess** — build the predictor variables (DFD 4.1).
3. **Train** a Multiple Linear Regression model (DFD 4.2).
4. **Evaluate** it on recent months it never trained on (DFD 4.3 → D6).
5. **Forecast** next month and **save** the results (DFD 4.4 → D5).

### Predictor variables (from the documentation)
- Past demand (previous month, and the month before — captures trend)
- Transaction volume (previous month)
- Inventory balance entering the month
- Inventory value entering the month
- Active projects scheduled for the month

Every predictor is something known **before** the forecast month begins, so
the model never sees the answer in advance.

### Evaluation
Metrics are computed on a **chronological hold-out** — the most recent months
are set aside for testing and never used for training. Time-series data is
never shuffled, because that would let the model learn from the future.
Reported metrics: **MAE, RMSE, MAPE, R²**.

### Why Multiple Linear Regression
It is interpretable. After a run, the model's coefficients show how each
factor affects demand — e.g. each additional active project adds roughly N
units of monthly demand. That transparency is the reason the paper chose MLR
over a black-box model.

---

## 7. API endpoints

These are URLs the frontend calls — not folders.

| Method | URL | Purpose |
|--------|-----|---------|
| GET | `/api/materials` | List materials (fills the forecast dropdown) |
| POST | `/api/aggregate` | Rebuild the monthly demand table from raw records |
| POST | `/api/forecast` | Train, evaluate, forecast next month, and save |

**What-if planning:** `POST /api/forecast` accepts an optional body such as
`{"overrides": {"active_projects": 12}}` to answer questions like *"if we take
on 12 projects next month, how much steel will we need?"*

---

## 7. Important notes

- **Sample data is not real data.** `seed_data.py` produces realistic but
  synthetic records so the system is demonstrable. Replace it with Parabellum's
  actual historical records when they are available.
- **Do not commit your password.** `config.py` is listed in `.gitignore`.
  Keep it that way before pushing to GitHub.
- **Login is now real** — but the demo accounts from `seed_users.py` are for
  development only. Change their passwords, or replace them with real
  accounts and disable the demo ones, before any real deployment.
- **Sharing the database with teammates:** the database itself is not in this
  folder (a database can't live in a zip). Each person runs `schema.sql`,
  then `python seed_users.py`, then `python seed_data.py` on their own
  machine. To share *real* data instead, use pgAdmin → right-click the
  database → **Backup…** to create a dump file.

---

## 8. Team

| Name | Role |
|------|------|
| Baluyot, Janna D. | Researcher |
| Corcega, Angelo Mchiel L. | Researcher |
| Dimayuga, John Neo B. | Researcher |
| Perez, Kurt Angelu P. | Researcher |

**Adviser:** Mr. Melandro V. Floro
