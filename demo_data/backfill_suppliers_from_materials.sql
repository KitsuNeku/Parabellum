-- =============================================================
-- Parabellum ISOS — Backfill Suppliers from existing materials
-- =============================================================
-- The new `suppliers` table (see add_suppliers_table.sql) starts EMPTY on
-- a live database - your existing supplier names have only ever lived as
-- free text on materials.supplier. This creates one real supplier record
-- for every distinct, non-blank supplier name already typed into your
-- materials, so the Suppliers page isn't empty and links up to Inventory
-- immediately (it matches by name).
--
-- Only fills in the Company Name + Status ('Active'). Contact person,
-- phone, email, address, category and payment terms are left blank -
-- edit each one from the Suppliers page (pencil icon) to fill those in
-- for real.
--
-- SAFE TO RE-RUN: only inserts a supplier whose name isn't already in
-- the table (case-insensitive match), so running this again after you've
-- started editing suppliers won't create duplicates or overwrite edits.
--
-- HOW TO USE:
--   1. Run add_suppliers_table.sql FIRST if you haven't already.
--   2. Open Supabase → SQL Editor → New Query.
--   3. Paste this entire file and click Run.
--   4. Reload the Suppliers page.
-- =============================================================

WITH next_names AS (
    SELECT DISTINCT TRIM(m.supplier) AS name
    FROM materials m
    WHERE m.supplier IS NOT NULL AND TRIM(m.supplier) != ''
      AND NOT EXISTS (
          SELECT 1 FROM suppliers s WHERE LOWER(TRIM(s.name)) = LOWER(TRIM(m.supplier))
      )
),
base AS (
    SELECT COALESCE(MAX(CAST(SUBSTRING(supplier_code FROM 5) AS INTEGER)), 400) AS n
    FROM suppliers WHERE supplier_code LIKE 'SUP-%'
)
INSERT INTO suppliers (supplier_code, name, status)
SELECT 'SUP-' || (base.n + ROW_NUMBER() OVER (ORDER BY next_names.name)), next_names.name, 'Active'
FROM next_names, base;

-- Sanity check — run separately to see what got added:
-- SELECT * FROM suppliers ORDER BY supplier_code;
