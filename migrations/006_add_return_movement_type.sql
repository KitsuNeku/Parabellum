-- =============================================================
-- Parabellum ISOS — Allow "RETURN" as a stock movement type
-- =============================================================
-- The Inventory module now records three kinds of stock movements:
--
--   RECEIPT   — Stock In:  material received from a supplier.
--   ISSUANCE  — Stock Out: material issued to a project / customer.
--   RETURN    — Back Order: material returned by a customer (goes
--                back onto the shelf, i.e. increases stock like a
--                RECEIPT, but is tracked separately so the summary
--                can show what came back vs. what was newly received).
--
-- The original stock_movements.movement_type CHECK constraint only
-- allowed the first two, so this script relaxes it to also allow
-- RETURN. Existing rows are untouched.
--
-- SAFE TO RE-RUN: DROP CONSTRAINT IF EXISTS makes this idempotent.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Inventory page — a new "Record Return" button and
--      a new "Back Orders (Returns)" table appear alongside Stock In
--      and Stock Out.
-- =============================================================

ALTER TABLE stock_movements
    DROP CONSTRAINT IF EXISTS stock_movements_movement_type_check;

ALTER TABLE stock_movements
    ADD CONSTRAINT stock_movements_movement_type_check
    CHECK (movement_type IN ('RECEIPT', 'ISSUANCE', 'RETURN'));
