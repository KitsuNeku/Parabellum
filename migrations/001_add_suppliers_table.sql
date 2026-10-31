-- =============================================================
-- Parabellum ISOS — Suppliers module
-- =============================================================
-- Adds the `suppliers` table backing the new Suppliers page (Supplier
-- Management) and grants every role that already has Inventory access
-- the new "suppliers" permission, so the sidebar link actually shows
-- up without an admin having to click it on in Settings first.
--
-- This is separate from materials.supplier (the free-text field
-- that's been on the Inventory page since the start) - it is NOT
-- touched or replaced. The Suppliers page links a supplier to its
-- materials by matching this table's `name` against materials.supplier,
-- so existing inventory rows link up automatically with no data
-- migration needed. Suppliers are deactivated, never deleted, so a
-- material's Stock In history always stays traceable.
--
-- SAFE TO RE-RUN: CREATE TABLE IF NOT EXISTS and the permissions UPDATE
-- (only appends "suppliers" if it isn't already in the list) make this
-- idempotent.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the app — "Suppliers" now appears in the sidebar under
--      Inventory & Sales for System Administrator and Inventory
--      Personnel.
-- =============================================================

CREATE TABLE IF NOT EXISTS suppliers (
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

-- Grant "suppliers" by default to the two roles that already manage
-- inventory/procurement. Only runs if role_permissions exists (it's
-- its own earlier migration) and only appends when missing, so this
-- never duplicates the key or clobbers an admin's own edits to other
-- modules.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'role_permissions') THEN
        UPDATE role_permissions
           SET permissions = permissions || ',suppliers'
         WHERE role IN ('System Administrator', 'Inventory Personnel')
           AND ',' || permissions || ',' NOT LIKE '%,suppliers,%';
    END IF;
END $$;
