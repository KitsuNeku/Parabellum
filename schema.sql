
DROP TABLE IF EXISTS support_messages, support_tickets, delivery_attempts, forecast_runs, company_settings, role_permissions, back_orders, chat_messages, audit_logs,
                     model_metrics, forecast_results, monthly_weather, monthly_demand,
                     stock_movements, transactions, projects, customers, suppliers, employees,
                     materials, users CASCADE;

-- ---- D1: User Records -------------------------------------------
CREATE TABLE users (
    user_id         SERIAL PRIMARY KEY,
    username        VARCHAR(60)  UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    full_name       VARCHAR(120),
    email           VARCHAR(150),
    department      VARCHAR(80),
    avatar_path     VARCHAR(255),
    role            VARCHAR(30)  NOT NULL DEFAULT 'Inventory Personnel'
                    CHECK (role IN ('System Administrator', 'Inventory Personnel',
                                    'Operations Personnel', 'Management/Owner')),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_attempts INT          NOT NULL DEFAULT 0,
    locked_until    TIMESTAMPTZ,
    custom_permissions TEXT,
    preferences     JSONB        NOT NULL DEFAULT '{}'::jsonb,
    totp_secret     VARCHAR(64),
    totp_enabled    BOOLEAN      NOT NULL DEFAULT FALSE,
    totp_last_step  BIGINT,
    must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_ip   VARCHAR(64),
    last_login_at   TIMESTAMPTZ,
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
    critical_level NUMERIC(12,2) NOT NULL DEFAULT 0,
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
    budget        NUMERIC(14,2) DEFAULT 0,
    priority      VARCHAR(20)  DEFAULT 'Medium',
    progress      INT          DEFAULT 0,
    staff         VARCHAR(40)
);

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
CREATE TABLE stock_movements (
    movement_id   SERIAL PRIMARY KEY,
    material_id   INT NOT NULL REFERENCES materials(material_id),
    movement_type VARCHAR(10) NOT NULL
                  CHECK (movement_type IN ('RECEIPT', 'ISSUANCE')),
    quantity      NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    movement_date DATE NOT NULL,
    project_id    INT REFERENCES projects(project_id),
    remarks       TEXT,
    recorded_by   VARCHAR(80),
    weather_temp_c       NUMERIC(5,2),
    weather_rainfall_mm  NUMERIC(8,2),
    weather_wind_kmh     NUMERIC(6,2),
    delivered_at           TIMESTAMPTZ,
    delivery_temp_c        NUMERIC(5,2),
    delivery_rainfall_mm   NUMERIC(8,2),
    delivery_wind_kmh      NUMERIC(6,2),
    delivery_failed_at       TIMESTAMPTZ,
    delivery_failure_reason  TEXT,
    delivery_attempts        INT NOT NULL DEFAULT 0,
    returned_at              TIMESTAMPTZ,
    returned_by              VARCHAR(80)
);
CREATE INDEX idx_movement_material_date
    ON stock_movements (material_id, movement_date);

-- ---- Back Orders (material returned by a customer/project) -----
CREATE TABLE back_orders (
    back_order_id SERIAL PRIMARY KEY,
    material_id   INT NOT NULL REFERENCES materials(material_id),
    quantity      NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    return_date   DATE NOT NULL,
    stock_out_ref VARCHAR(120),
    remarks       TEXT,
    back_order_by VARCHAR(120),
    recorded_by   VARCHAR(80),
    disposition   VARCHAR(20)
                  CHECK (disposition IS NULL OR disposition IN ('Reimbursed', 'Replaced')),
    restocked     BOOLEAN NOT NULL DEFAULT FALSE,
    restocked_qty      NUMERIC(12,2) NOT NULL DEFAULT 0,
    replaced_qty        NUMERIC(12,2) CHECK (replaced_qty IS NULL OR replaced_qty > 0),
    reimbursed_amount    NUMERIC(12,2) CHECK (reimbursed_amount IS NULL OR reimbursed_amount > 0),
    disposition_notes    TEXT
);
CREATE INDEX idx_back_order_material_date
    ON back_orders (material_id, return_date);

-- ---- D4: Monthly Demand Records (forecasting-ready panel) -------
CREATE TABLE monthly_demand (
    id                 SERIAL PRIMARY KEY,
    material_id        INT  NOT NULL REFERENCES materials(material_id),
    period_month       DATE NOT NULL,
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
    employee_code    VARCHAR(20)  UNIQUE NOT NULL,
    name             VARCHAR(120) NOT NULL,
    role             VARCHAR(80),
    commission_rate  NUMERIC(5,2) DEFAULT 0,
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

-- ---- Chat: one-to-one messages between accounts ------------------
CREATE TABLE chat_messages (
    message_id   SERIAL PRIMARY KEY,
    sender_id    INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    recipient_id INT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    body         TEXT NOT NULL CHECK (char_length(body) BETWEEN 1 AND 500),
    sent_at      TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    read_at      TIMESTAMPTZ,
    CHECK (sender_id <> recipient_id)
);
CREATE INDEX idx_chat_pair   ON chat_messages (sender_id, recipient_id, message_id);
CREATE INDEX idx_chat_unread ON chat_messages (recipient_id) WHERE read_at IS NULL;

-- ---- Customer support tickets ----
CREATE TABLE support_tickets (
    ticket_id        SERIAL PRIMARY KEY,
    token_hash       CHAR(64) NOT NULL UNIQUE,
    company          VARCHAR(150),
    contact_name     VARCHAR(120) NOT NULL,
    email            VARCHAR(150) NOT NULL,
    phone            VARCHAR(40)  NOT NULL,
    order_ref        VARCHAR(60),
    transaction_id   INT REFERENCES transactions(transaction_id) ON DELETE SET NULL,
    status           VARCHAR(12)  NOT NULL DEFAULT 'Open' CHECK (status IN ('Open','Answered','Closed')),
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    staff_read_at    TIMESTAMPTZ,
    customer_read_at TIMESTAMPTZ,
    closed_at        TIMESTAMPTZ,
    closed_by        VARCHAR(120)
);
CREATE INDEX idx_support_tickets_status ON support_tickets (status, updated_at DESC);

CREATE TABLE support_messages (
    message_id     SERIAL PRIMARY KEY,
    ticket_id      INT NOT NULL REFERENCES support_tickets(ticket_id) ON DELETE CASCADE,
    sender         VARCHAR(10) NOT NULL CHECK (sender IN ('customer','staff')),
    staff_user_id  INT REFERENCES users(user_id) ON DELETE SET NULL,
    staff_name     VARCHAR(120),
    body           TEXT NOT NULL,
    sent_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_support_messages_ticket ON support_messages (ticket_id, message_id);

-- ---- Role default permissions (Settings > Roles & Permissions) ---
CREATE TABLE role_permissions (
    role        VARCHAR(30) PRIMARY KEY
                CHECK (role IN ('System Administrator', 'Inventory Personnel',
                                'Operations Personnel', 'Management/Owner')),
    permissions TEXT NOT NULL
);

INSERT INTO role_permissions (role, permissions) VALUES
    ('System Administrator', 'dashboard,inventory,outlook,suppliers,customers,projects,transactions,support,forecasting,reports,settings,profile'),
    ('Inventory Personnel',  'dashboard,inventory,outlook,suppliers,profile'),
    ('Operations Personnel', 'dashboard,projects,transactions,support,profile'),
    ('Management/Owner',     'dashboard,outlook,projects,transactions,support,forecasting,reports,profile');

-- ---- Company settings (Settings > Company) ----
CREATE TABLE company_settings (
    id           INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    company_name VARCHAR(150) NOT NULL DEFAULT 'Parabellum Steel & Iron Works',
    tin          VARCHAR(30),
    email        VARCHAR(150),
    phone        VARCHAR(40),
    address      VARCHAR(250),
    currency     VARCHAR(10)  NOT NULL DEFAULT 'PHP',
    vat_rate     NUMERIC(5,2) NOT NULL DEFAULT 12 CHECK (vat_rate >= 0 AND vat_rate <= 100),
    session_timeout_min INT  NOT NULL DEFAULT 30,
    require_2fa_admins BOOLEAN NOT NULL DEFAULT FALSE,
    login_alerts BOOLEAN      NOT NULL DEFAULT FALSE,
    last_digest_at TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP,
    updated_by   VARCHAR(60)
);
INSERT INTO company_settings (id, company_name, email, address)
VALUES (1, 'Parabellum Steel & Iron Works', 'info@parabellumsteel.ph', 'Lipa City, Batangas, Philippines');

-- ---- Material supplier link ----
ALTER TABLE materials ADD COLUMN supplier_id INT REFERENCES suppliers(supplier_id) ON DELETE SET NULL;

-- ---- Forecast runs ----
CREATE TABLE forecast_runs (
    run_id  SERIAL PRIMARY KEY,
    run_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    run_by  VARCHAR(60),
    result  JSONB NOT NULL
);

-- ---- Delivery attempts ----
CREATE TABLE delivery_attempts (
    attempt_id   SERIAL PRIMARY KEY,
    movement_id  INT NOT NULL REFERENCES stock_movements(movement_id) ON DELETE CASCADE,
    outcome      VARCHAR(12) NOT NULL CHECK (outcome IN ('Delivered', 'Failed')),
    reason       TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temp_c       NUMERIC(5,2),
    rainfall_mm  NUMERIC(8,2),
    wind_kmh     NUMERIC(6,2),
    recorded_by  VARCHAR(80)
);
CREATE INDEX idx_delivery_attempts_movement ON delivery_attempts (movement_id);
