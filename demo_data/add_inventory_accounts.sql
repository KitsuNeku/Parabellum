-- =============================================================
-- Parabellum ISOS — Add two Inventory-only user accounts
-- =============================================================
-- Creates two "Inventory Personnel" accounts:
--   John Erick Ramos  (username: jramos)
--   Ronnel Bautista    (username: rbautista)
--
-- The "Inventory Personnel" role (defined in auth.py / data.js
-- ROLE_PERMISSIONS) only grants access to Dashboard, Inventory, and
-- Profile — no Customers, Projects, Transactions, Forecasting,
-- Reports, or Settings. That is the correct, already-built role for
-- "inventory only accounts" — nothing else needed to change.
--
-- Password hashes below were generated with the SAME werkzeug
-- generate_password_hash() function the app itself uses (scrypt),
-- so these accounts log in exactly like any other seeded account.
-- Plain-text passwords (share with the two employees, then have them
-- change it after first login if you add that flow later):
--
--   jramos     / Ramos!2026warehouse
--   rbautista  / Bautista!2026warehouse
--
-- SAFE TO RE-RUN: ON CONFLICT (username) DO UPDATE means running this
-- twice just re-syncs the same two accounts, it does not duplicate them.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Log in with either username/password above — the left nav will
--      only show Dashboard, Inventory, and Profile.
-- =============================================================

INSERT INTO users (username, password_hash, full_name, role, email, department)
VALUES
    (
        'jramos',
        'scrypt:32768:8:1$QiHz27XAHK6AIpRt$dea81fcfb4bd2e7111e6c2dedc667514129fbcb8d0ea92d63b6ae7f38c57262ced92a9519a48e320e93bb1467aa9470b3a063809cf0e82e982fe487de2c685a0',
        'John Erick Ramos',
        'Inventory Personnel',
        'jramos@parabellumsteel.com.ph',
        'Warehouse'
    ),
    (
        'rbautista',
        'scrypt:32768:8:1$vASybDFsCB43GCGB$c34a806dc373bfea7f32acf22b45f5bcd7e10c8e88e9ae0faa242e4dd715aa9e94bfe86904e1c7c1e5830d23c5fd569a665843a4fa25eebc2595aaa866b1fb27',
        'Ronnel Bautista',
        'Inventory Personnel',
        'rbautista@parabellumsteel.com.ph',
        'Warehouse'
    )
ON CONFLICT (username) DO UPDATE SET
    password_hash   = EXCLUDED.password_hash,
    full_name       = EXCLUDED.full_name,
    role            = EXCLUDED.role,
    email           = EXCLUDED.email,
    department      = EXCLUDED.department,
    is_active       = TRUE,
    failed_attempts = 0,
    locked_until    = NULL;
