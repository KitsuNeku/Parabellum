-- =============================================================
-- Parabellum ISOS — Fill in supplier contact details
-- =============================================================
-- backfill_suppliers_from_materials.sql only created bare records (name +
-- "Active" status) for the supplier names already typed into your
-- materials. This fills in the rest - contact person, phone, email,
-- address, category and payment terms - for the standard supplier set
-- (SteelAsia, Capitol Steel, Pag-asa Steel, Cathay Metal, Puyat Steel,
-- Treasure Steelworks).
--
-- Matches by NAME (case-insensitive), not by code, so it works whichever
-- SUP-xxx code your database assigned. Only updates a supplier whose
-- row is currently blank for these fields (COALESCE/NULLIF guards below),
-- so it will NOT overwrite anything you've already edited by hand on the
-- Suppliers page - safe to re-run any time.
--
-- Only covers the 6 names above. Any OTHER supplier name you've typed
-- into materials (not in this list) is untouched here - edit those from
-- the Suppliers page directly (pencil icon).
--
-- HOW TO USE:
--   1. Run backfill_suppliers_from_materials.sql FIRST if you haven't.
--   2. Open Supabase → SQL Editor → New Query.
--   3. Paste this entire file and click Run.
--   4. Reload the Suppliers page.
-- =============================================================

UPDATE suppliers SET
    contact_person = COALESCE(NULLIF(TRIM(suppliers.contact_person), ''), v.contact),
    phone           = COALESCE(NULLIF(TRIM(suppliers.phone), ''), v.phone),
    email           = COALESCE(NULLIF(TRIM(suppliers.email), ''), v.email),
    address         = COALESCE(NULLIF(TRIM(suppliers.address), ''), v.address),
    category        = COALESCE(NULLIF(TRIM(suppliers.category), ''), v.category),
    terms           = COALESCE(NULLIF(TRIM(suppliers.terms), ''), v.terms),
    remarks         = COALESCE(NULLIF(TRIM(suppliers.remarks), ''), v.remarks)
FROM (VALUES
    ('SteelAsia',           'Roberto Villanueva', '0917-552-0181', 'sales@steelasia.sample.ph',     'Calaca, Batangas',    'Raw Material Supplier',      'Net 30',           'Primary rebar and H-beam source.'),
    ('Capitol Steel',       'Melissa Go',          '0918-334-7720', 'orders@capitolsteel.sample.ph', 'Valenzuela City',     'Raw Material Supplier',      'Net 30',           NULL),
    ('Pag-asa Steel',       'Arnel Bautista',      '0920-118-4456', 'supply@pagasasteel.sample.ph',  'Bulacan',             'Raw Material Supplier',      'Net 45',           'Angle bars and pipes.'),
    ('Cathay Metal',        'Jenny Lao',           '0915-660-2394', 'cathay.orders@sample.ph',       'Binondo, Manila',     'Hardware/Fastener Supplier', 'Cash on Delivery', 'Fasteners, consumables, stainless.'),
    ('Puyat Steel',         'Dennis Ramos',        '0917-904-6613', 'sales@puyatsteel.sample.ph',    'Mandaluyong City',    'Raw Material Supplier',      'Net 30',           'GI sheets and purlins.'),
    ('Treasure Steelworks', 'Lorna Castillo',      '0919-275-3308', 'treasure.steel@sample.ph',      'Lipa City, Batangas', 'Raw Material Supplier',      'Net 15',           'On pause pending price review.')
) AS v(name, contact, phone, email, address, category, terms, remarks)
WHERE LOWER(TRIM(suppliers.name)) = LOWER(v.name);

-- Sanity check — run separately to confirm:
-- SELECT supplier_code, name, contact_person, phone, email, address, category, terms, remarks FROM suppliers ORDER BY supplier_code;
