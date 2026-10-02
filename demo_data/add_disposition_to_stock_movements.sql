-- =============================================================
-- Parabellum ISOS — Track what happened to a back-ordered item
-- =============================================================
-- The Back Orders table's Actions column used to show the same View /
-- Print / Delete buttons as Stock In and Stock Out, but a back order
-- isn't something you "delete" the way you'd delete a stock movement —
-- what actually matters once an item comes back from a customer is what
-- staff decide to DO with it. This adds a real column so that decision
-- (Refurbished or Returned) can be recorded and shown as a checkmark
-- directly on the Back Orders row, instead of being buried in Remarks.
--
-- Only meaningful for movement_type = 'RETURN' rows. It does NOT change
-- materials.current_stock either way — a back order still never adds to
-- on-hand stock (see _apply_movement() in app.py); this column is purely
-- a record of what the business did with the physical item afterward.
--
-- SAFE TO RE-RUN: ADD COLUMN IF NOT EXISTS makes this idempotent.
-- Existing RETURN rows are untouched and get disposition = NULL (i.e.
-- "not yet marked") — nothing you've already recorded is changed.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Inventory page — the Back Orders table's Actions column
--      now shows "Refurbished" / "Returned" checkmarks instead of the
--      old View/Print/Delete icons.
-- =============================================================

ALTER TABLE stock_movements
    ADD COLUMN IF NOT EXISTS disposition VARCHAR(20);

-- Keep the same two allowed values as a fresh install's schema.sql. The
-- DO block skips re-adding the constraint if this script is run twice.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'stock_movements_disposition_check'
    ) THEN
        ALTER TABLE stock_movements
            ADD CONSTRAINT stock_movements_disposition_check
            CHECK (disposition IS NULL OR disposition IN ('Refurbished', 'Returned'));
    END IF;
END $$;
