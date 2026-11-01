# Parabellum ISOS
### Inventory and Service Optimization System for Demand Forecasting and Operational Efficiency
Parabellum Steel and Iron Works — Capstone Project

A web-based system that centralizes inventory, suppliers, customers, projects,
client transactions and reporting, with a machine-learning module that
forecasts **next month's demand for each material** using Multiple Linear
Regression (MLR).

---

## 1. Technology

| Component | Technology |
|-----------|-----------|
| Frontend | HTML, CSS, JavaScript, Bootstrap 5, Chart.js |
| Backend | Python + Flask (Blueprints) |
| Database | PostgreSQL (Supabase or local pgAdmin) |
| Forecasting | scikit-learn (Multiple Linear Regression), pandas, NumPy |
| Weather data | Open-Meteo API (Lipa City, Batangas) |
| Reports | ReportLab (PDF), openpyxl (Excel) |
| Hosting | Gunicorn on Render |

## 2. Project structure

```
Parabellum/
├── app.py              App setup, page routes, error handling
├── config.py           Database credentials + settings
├── db.py               Database helpers + audit log
├── auth.py             Login, sessions, role permissions
├── security.py         Security headers, CSRF, rate limiting
├── mlr_model.py        Monthly demand forecasting (MLR)
├── weather_api.py      Open-Meteo weather sync
├── scheduler.py        Nightly automatic retrain (2:00 AM)
├── backup.py           Settings > Backup & Restore
├── reports_export.py   PDF / Excel report builders
├── seed_users.py       Demo accounts (one per role)
├── seed_data.py        30 months of sample data
├── schema.sql          Full database schema
├── routes/             API endpoints, one file per module
│   ├── auth_api.py  dashboard.py  chat.py  profile.py
│   ├── inventory.py outlook.py    support.py    suppliers.py  customers.py  projects.py
│   └── transactions.py users.py settings.py reports.py forecast.py
├── templates/
│   ├── layout.html     Shared sidebar, top bar and footer
│   └── <page>.html     One template per page (extends layout.html)
├── static/
│   ├── css/styles.css
│   └── js/
│       ├── app.js, data.js, charts.js, chat.js   shared scripts
│       └── pages/<page>.js                        page-specific scripts
├── migrations/         Upgrades for databases created with an older schema
└── demo_data/          Training datasets (see demo_data/README.md)
```

## 3. Setup

1. `pip install -r requirements.txt`
2. Set the database connection in `config.py` (or the `DB_*` environment variables).
3. New database: run `schema.sql` in the Supabase SQL Editor or pgAdmin.
4. `python seed_users.py` — creates one demo account per role and prints the logins.
5. Optional: `python seed_data.py` for sample data, or load a dataset from `demo_data/`.
6. `python app.py` and open http://127.0.0.1:5000

Existing database created with an older `schema.sql`: run the files in
`migrations/` in number order instead of step 3.

## 4. Roles

| Role | Pages |
|------|-------|
| System Administrator | All pages |
| Inventory Personnel | Dashboard, Inventory, Stock Outlook, Suppliers, Profile |
| Operations Personnel | Dashboard, Projects, Transactions, Customer Support, Profile |
| Management/Owner | Dashboard, Stock Outlook, Projects, Transactions, Customer Support (view only), Forecasting, Reports, Profile |

Role defaults can be changed in Settings > User Management, and per-user
overrides are supported. Access is enforced on the server, not only by hiding
sidebar links.

## 5. Forecasting

Process (matches the DFD, processes 3.0 and 4.0):

1. **Sync weather**: monthly weather for Lipa City is downloaded from Open-Meteo.
2. **Aggregate** Stock Out (issuance) records into monthly demand per material.
3. **Build features** for each material-month.
4. **Evaluate**: train on older months, test on the most recent 3-6 months the model never saw.
5. **Forecast** next month's demand and save the results.

Features:
- Demand in the previous month and the month before
- Month of the year (sine/cosine cycle)
- Total rainfall and number of rainy days in the month

Evaluation compares three models on the same test months: the MLR, the same MLR without
the weather inputs, and a naive guess (next month = last month). MAE, RMSE, MAPE and R²
are reported for each, so the effect of weather is measured instead of assumed.

Model selection: each material with at least 15 months of history gets its own MLR; materials
with less history use one combined MLR across all materials.

Recommended restock = predicted demand − current stock. Status is *Will run out* when stock is
below the predicted demand and *Low* when it is within 25% of it.

The forecast runs automatically every night at 2:00 AM (Philippine time) and can be run
manually with **Run Forecast**. The page shows the latest saved run.

## 6. Security

- Hashed passwords (werkzeug), signed HttpOnly session cookies
- Session timeout set in Settings > Security (15 min to 2 hours of inactivity)
- Two-factor authentication with any authenticator app (My Profile); can be required for administrators
- Admin password reset with a one-time temporary password the user must change
- Deactivated accounts are signed out within a minute
- Login alerts by email when an account signs in from a new location
- Account lockout for 15 minutes after 5 failed logins
- Server-side role checks on every page and API
- CSRF tokens on every state-changing request
- Rate limiting (login, forecasting, report export)
- Security headers (CSP, X-Frame-Options, HSTS, nosniff)
- Every login attempt and important action is written to the audit trail

## 7. How to use

**Stock Outlook (sidebar, below Inventory)**
- Lists every material with current stock, critical level, reorder level, status,
  next month's forecast and the recommended restock (forecast minus current stock).
- Status: Out of Stock, Critical (at or below critical level), Low (at or below reorder level), OK.
- Critical level is set per material by a System Administrator (click the value).
  It is the lowest the stock should ever reach; reorder level stays as the "time to buy" mark.
- Delivery Risk shows today's and tomorrow's weather in Lipa City and the chance a
  delivery fails. Once a weather type (Dry, Light rain, Heavy rain) has at least 5
  recorded deliveries, the risk comes from their failure rate (under 15% Low,
  under 35% Medium, else High). Before that it uses the weather alone. Wind of
  50 km/h or more raises the risk one level.

**Customer Support (service management)**
1. On the landing page a customer clicks **Need Support?** (or the chat button at the bottom right).
2. They fill in company (optional), name, email, phone, order/transaction no. (optional) and their concern.
3. On submit they get a ticket number (e.g. TKT-0001) and the chat opens. The chat stays in that browser;
   on another device they use **Already have a ticket?** with the ticket number and email.
4. Staff answer in **Customer Support** in the sidebar. Statuses: Open (customer waiting),
   Answered (staff replied), Closed. A new customer message reopens a closed ticket.
5. Administrators and Operations Personnel can reply and close tickets; Management can view.
   If an order no. matches a transaction (TXN-0012), its details are shown beside the chat.
6. When email is set up (section 8), the customer gets the ticket number and every staff reply by email.

**Deliveries (Inventory > Stock Out, or Stock Outlook)**
1. A new Stock Out starts as **Pending**.
2. **Delivered** finishes it. **Failed** asks for a reason and puts it on **Standby**.
   Materials on standby are not back in inventory.
3. From Standby: **Re-deliver** (back to Pending) or **Return to inventory**
   (quantity goes back to stock and the Stock Out no longer counts as demand in the forecast).
4. Every attempt is saved with the day's weather, which feeds the Delivery Risk.


**Two-factor authentication (2FA)**
1. Install Google Authenticator or Microsoft Authenticator on your phone.
2. My Profile > Two-Factor Authentication > **Turn On**, scan the QR code, enter the 6-digit code.
3. From then on, sign-in asks for the current code from the app.
4. To turn it off: enter your password and a current code in the same card.

**Lost phone / reset 2FA**
- Another administrator: Settings > User Management > phone icon (Reset 2FA) on that user.
- If you are the only administrator, run in the project folder:
  ```
  venv/bin/python -c "from db import execute_query; from config import DB_CONFIG; execute_query(DB_CONFIG, \"UPDATE users SET totp_enabled=FALSE, totp_secret=NULL WHERE username='admin'\")"
  ```

**Forgotten password**
- An administrator opens Settings > User Management > key icon (Reset Password). A one-time
  temporary password is shown; the user must set a new password right after signing in.

## 8. Email (login alerts and weekly digest)

Emails are sent only when these environment variables are set (on Render: Environment tab;
locally: `export` them before `python app.py`):

```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=youraccount@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=youraccount@gmail.com
```

For Gmail, create an App Password (Google Account > Security > 2-Step Verification > App passwords).
The weekly digest goes out every Monday at 8:00 AM (Philippine time) to users who turned it on.

## 9. Notes

- `seed_data.py` and most of `demo_data/` are synthetic data. See
  `demo_data/README.md` for which rows are real.
- Demo accounts are for development and defense only.

## 10. Team

| Name | Role |
|------|------|
| Baluyot, Janna D. | Researcher |
| Corcega, Angelo Mchiel L. | Researcher |
| Dimayuga, John Neo B. | Researcher |
| Perez, Kurt Angelu P. | Researcher |

**Adviser:** Mr. Melandro V. Floro
