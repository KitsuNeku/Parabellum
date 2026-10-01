-- =================================================================
-- Parabellum ISOS — Database Schema
-- Maps directly to the data stores in your Data Flow Diagram.
--
-- Run in pgAdmin:  right-click your database > Query Tool > paste > F5
-- =================================================================

DROP TABLE IF EXISTS audit_logs, model_metrics, forecast_results,
                     monthly_weather, monthly_demand, stock_movements, transactions,
                     projects, customers, suppliers, employees, materials, users CASCADE;

-- ---- D1: User Records -------------------------------------------
CREATE TABLE users (
    user_id         SERIAL PRIMARY KEY,
    username        VARCHAR(60)  UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    full_name       VARCHAR(120),
    email           VARCHAR(150),
    department      VARCHAR(80),
    avatar_path     VARCHAR(255),
    -- These four values MUST exactly match the keys in ROLE_PERMISSIONS
    -- in both static/js/data.js (frontend) and auth.py (backend). A
    -- mismatch here silently locks everyone out of everything, the same
    -- class of bug as the sidebar-link issue fixed earlier.
    role            VARCHAR(30)  NOT NULL DEFAULT 'Inventory Personnel'
                    CHECK (role IN ('System Administrator', 'Inventory Personnel',
                                    'Operations Personnel', 'Management/Owner')),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_attempts INT          NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    -- Per-user access override (Settings > Users > Access). Comma-separated
    -- list of page keys drawn from ROLE_PERMISSIONS (dashboard, inventory,
    -- customers, projects, transactions, forecasting, reports, settings,
    -- profile). NULL = use the role's defaults; any value REPLACES them for
    -- this one user only. Kept as TEXT (not JSON/array) so it's readable and
    -- editable with plain SQL when needed.
    custom_permissions TEXT,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ---- D2: Material Records (material master) ---------------------
CREATE TABLE materials (
    material_id   SERIAL PRIMARY KEY,
    material_code VARCHAR(40)  UNIQUE NOT NULL,
    material_name VARCHAR(150) NOT NULL,
    unit          VARCHAR(20)  NOT NULL,
    unit_cost     NUMERIC(12,2) NOT NULL DEFAULT 0,
    current_stock NUMERIC(12,2) NOT NULL DEFAULT 0,
    reorder_level NUMERIC(12,2) NOT NULL DEFAULT 0,
    -- Descriptive fields shown on the inventory page.
    category      VARCHAR(40)  DEFAULT 'Uncategorized',
    supplier      VARCHAR(80),
    location      VARCHAR(60)  DEFAULT 'Warehouse A',
    added_date    DATE         DEFAULT CURRENT_DATE
);

-- ---- Customers -------------------------------------------------
CREATE TABLE customers (
    customer_id    SERIAL PRIMARY KEY,
    customer_code  VARCHAR(40)  UNIQUE NOT NULL,
    name           VARCHAR(150) NOT NULL,
    contact_person VARCHAR(120),
    phone          VARCHAR(40),
    email          VARCHAR(120),
    address        VARCHAR(200),
    status         VARCHAR(20)  DEFAULT 'Active',
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ---- Suppliers --------------------------------------------------
-- Companies Parabellum buys materials from (Suppliers page). Kept as
-- its own table, separate from materials.supplier (a free-text field
-- that's been on `materials` since the start) rather than replacing
-- it, so existing material rows keep working unchanged - the Suppliers
-- page links to materials by matching this table's `name` against
-- materials.supplier, the same way the Customers/Projects link works
-- by code. Suppliers are deactivated, never deleted, so a material's
-- Stock In history always stays traceable back to who supplied it.
CREATE TABLE suppliers (
    supplier_id    SERIAL PRIMARY KEY,
    supplier_code  VARCHAR(40)  UNIQUE NOT NULL,
    name           VARCHAR(150) NOT NULL,
    contact_person VARCHAR(120),
    phone          VARCHAR(40),
    email          VARCHAR(120),
    address        VARCHAR(200),
    category       VARCHAR(60),
    terms          VARCHAR(30)  DEFAULT 'Net 30',
    status         VARCHAR(20)  NOT NULL DEFAULT 'Active'
                   CHECK (status IN ('Active', 'Inactive', 'Archived')),
    remarks        TEXT,
    created_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
);

-- ---- Projects (source of the "project activity" predictor) ------
CREATE TABLE projects (
    project_id    SERIAL PRIMARY KEY,
    project_code  VARCHAR(40)  UNIQUE,
    project_name  VARCHAR(150) NOT NULL,
    customer_name VARCHAR(150),
    customer_id   INT REFERENCES customers(customer_id),
    start_date    DATE NOT NULL,
    end_date      DATE,
    status        VARCHAR(30) DEFAULT 'Ongoing',
    -- Extra fields shown on the projects page.
    budget        NUMERIC(14,2) DEFAULT 0,
    priority      VARCHAR(20)  DEFAULT 'Medium',
    progress      INT          DEFAULT 0,
    staff         VARCHAR(40)
);

-- ---- Transactions (source of the "transaction volume" predictor)-
CREATE TABLE transactions (
    transaction_id SERIAL PRIMARY KEY,
    project_id     INT REFERENCES projects(project_id),
    customer_id    INT REFERENCES customers(customer_id),
    customer_name  VARCHAR(150),
    txn_date       DATE NOT NULL,
    amount         NUMERIC(14,2) DEFAULT 0,
    material_name  VARCHAR(150),
    quantity       NUMERIC(12,2) DEFAULT 0,
    unit_price     NUMERIC(12,2) DEFAULT 0,
    payment_status VARCHAR(20)  DEFAULT 'Pending',
    payment_method VARCHAR(40)
);

-- ---- D3: Stock Movement Records (receipts + issuances) ----------
-- Material ISSUANCES are what we treat as demand.
CREATE TABLE stock_movements (
    movement_id   SERIAL PRIMARY KEY,
    material_id   INT NOT NULL REFERENCES materials(material_id),
    movement_type VARCHAR(10) NOT NULL
                  CHECK (movement_type IN ('RECEIPT', 'ISSUANCE', 'RETURN')),
    quantity      NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    movement_date DATE NOT NULL,
    project_id    INT REFERENCES projects(project_id),
    remarks       TEXT,
    recorded_by   VARCHAR(80),  -- display name of the user who performed this movement
    -- Only meaningful for movement_type = 'RETURN': a damaged return is
    -- still logged (so the Back Orders table/report shows it came back),
    -- but is NOT added to materials.current_stock - see _apply_movement()
    -- in app.py. Always FALSE for RECEIPT/ISSUANCE rows.
    is_damaged    BOOLEAN NOT NULL DEFAULT FALSE,
    -- Only meaningful for movement_type = 'RETURN': the customer or
    -- project that returned the material, i.e. who initiated the back
    -- order. Kept separate from recorded_by (the staff member who typed
    -- it in) and from remarks (free-text reason for the return).
    back_order_by VARCHAR(120)
);
CREATE INDEX idx_movement_material_date
    ON stock_movements (material_id, movement_date);

-- ---- D4: Monthly Demand Records (forecasting-ready panel) -------
-- Built by aggregate_monthly_demand() — DFD process 3.2.
CREATE TABLE monthly_demand (
    id                 SERIAL PRIMARY KEY,
    material_id        INT  NOT NULL REFERENCES materials(material_id),
    period_month       DATE NOT NULL,          -- first day of the month
    demand_qty         NUMERIC(12,2) NOT NULL DEFAULT 0,
    transaction_volume INT           NOT NULL DEFAULT 0,
    inventory_balance  NUMERIC(12,2) NOT NULL DEFAULT 0,
    inventory_value    NUMERIC(14,2) NOT NULL DEFAULT 0,
    active_projects    INT           NOT NULL DEFAULT 0,
    CONSTRAINT uq_monthly_demand UNIQUE (material_id, period_month)
);

-- ---- D8: Monthly Weather Records ---------------------------------
CREATE TABLE monthly_weather (
    id                 SERIAL PRIMARY KEY,
    period_month       DATE NOT NULL,
    location           VARCHAR(100) NOT NULL DEFAULT 'Lipa City, Batangas, PH',
    avg_temp_c         NUMERIC(5,2),
    total_rainfall_mm  NUMERIC(8,2),
    rainy_days         INT,
    max_wind_kmh       NUMERIC(6,2),
    fetched_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_monthly_weather UNIQUE (period_month, location)
);

-- ---- D5: Forecast Records ---------------------------------------
CREATE TABLE forecast_results (
    forecast_id      SERIAL PRIMARY KEY,
    material_id      INT  NOT NULL REFERENCES materials(material_id),
    forecast_month   DATE NOT NULL,
    predicted_demand NUMERIC(12,2) NOT NULL,
    model_name       VARCHAR(80) NOT NULL DEFAULT 'Multiple Linear Regression',
    generated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_forecast UNIQUE (material_id, forecast_month, model_name)
);

-- ---- D6: Model Evaluation Records -------------------------------
CREATE TABLE model_metrics (
    metric_id     SERIAL PRIMARY KEY,
    model_name    VARCHAR(80) NOT NULL,
    mae           NUMERIC(14,6),
    rmse          NUMERIC(14,6),
    mape          NUMERIC(14,6),
    r2            NUMERIC(14,6),
    train_rows    INT,
    test_rows     INT,
    features_used TEXT,
    evaluated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---- Employees (for commission computation) ---------------------
CREATE TABLE employees (
    employee_id      SERIAL PRIMARY KEY,
    employee_code    VARCHAR(20)  UNIQUE NOT NULL,  -- matches projects.staff (e.g. "EMP-01")
    name             VARCHAR(120) NOT NULL,
    role             VARCHAR(80),
    commission_rate  NUMERIC(5,2) DEFAULT 0,          -- percent, e.g. 4.50
    status           VARCHAR(20)  DEFAULT 'Active'
);

-- ---- D7: Reports and Audit Logs ---------------------------------
CREATE TABLE audit_logs (
    log_id    SERIAL PRIMARY KEY,
    username  VARCHAR(80),
    action    VARCHAR(120) NOT NULL,
    details   TEXT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---- Role default permissions (Settings > Roles & Permissions) ---
-- Lets an admin edit which modules each ROLE gets by default, from the
-- UI, instead of that being frozen in Python code. A per-user override
-- (users.custom_permissions above) still wins over whatever is here for
-- that one user. One row per role; `permissions` is the same
-- comma-separated page-key format as custom_permissions. Seeded with the
-- same defaults auth.py shipped with, so behavior doesn't change until
-- someone actually edits a cell in the matrix.
CREATE TABLE role_permissions (
    role        VARCHAR(30) PRIMARY KEY
                CHECK (role IN ('System Administrator', 'Inventory Personnel',
                                'Operations Personnel', 'Management/Owner')),
    permissions TEXT NOT NULL
);

INSERT INTO role_permissions (role, permissions) VALUES
    ('System Administrator', 'dashboard,inventory,suppliers,customers,projects,transactions,forecasting,reports,settings,profile'),
    ('Inventory Personnel',  'dashboard,inventory,suppliers,profile'),
    ('Operations Personnel', 'dashboard,projects,transactions,profile'),
    ('Management/Owner',     'dashboard,projects,transactions,forecasting,reports,profile');
