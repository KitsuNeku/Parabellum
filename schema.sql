-- =================================================================
-- Parabellum ISOS — Database Schema
-- Maps directly to the data stores in your Data Flow Diagram.
--
-- Run in pgAdmin:  right-click your database > Query Tool > paste > F5
-- =================================================================

DROP TABLE IF EXISTS audit_logs, model_metrics, forecast_results,
                     monthly_demand, stock_movements, transactions,
                     projects, customers, employees, materials, users CASCADE;

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
                  CHECK (movement_type IN ('RECEIPT', 'ISSUANCE')),
    quantity      NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    movement_date DATE NOT NULL,
    project_id    INT REFERENCES projects(project_id),
    remarks       TEXT
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
