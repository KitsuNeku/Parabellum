-- =============================================================
-- Parabellum ISOS — Editable role default permissions
-- =============================================================
-- Adds a `role_permissions` table so an administrator can edit which
-- modules each ROLE gets by default from Settings > Roles & Permissions,
-- instead of that being frozen in Python code (auth.py's old
-- ROLE_PERMISSIONS dict, which is now only a fallback if this table is
-- ever empty). A per-user override (users.custom_permissions) still
-- wins over whatever is here for that one user.
--
-- SAFE TO RE-RUN: CREATE TABLE IF NOT EXISTS + the INSERT only seeds
-- rows that don't already exist (ON CONFLICT DO NOTHING), so running
-- this twice — or on a database that already has the table from a
-- fresh schema.sql — does nothing destructive either time.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload Settings > Roles & Permissions — the checkmarks/dashes
--      should now be clickable buttons that save immediately.
-- =============================================================

CREATE TABLE IF NOT EXISTS role_permissions (
    role        VARCHAR(30) PRIMARY KEY
                CHECK (role IN ('System Administrator', 'Inventory Personnel',
                                'Operations Personnel', 'Management/Owner')),
    permissions TEXT NOT NULL
);

INSERT INTO role_permissions (role, permissions) VALUES
    ('System Administrator', 'dashboard,inventory,customers,projects,transactions,forecasting,reports,settings,profile'),
    ('Inventory Personnel',  'dashboard,inventory,profile'),
    ('Operations Personnel', 'dashboard,projects,transactions,profile'),
    ('Management/Owner',     'dashboard,projects,transactions,forecasting,reports,profile')
ON CONFLICT (role) DO NOTHING;

-- Optional sanity check — run this separately to confirm the fix:
-- SELECT * FROM role_permissions ORDER BY role;
