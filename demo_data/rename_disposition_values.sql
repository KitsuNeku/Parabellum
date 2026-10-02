-- =============================================================
-- Parabellum ISOS — Rename back-order disposition labels
-- =============================================================
-- stock_movements.disposition originally used the labels "Refurbished"
-- and "Returned". They've been renamed to "Reimbursed" and "Replaced"
-- to better match what staff are actually recording. Run this ONLY if
-- you already ran an earlier version of add_disposition_to_stock_movements.sql
-- (i.e. you already have a `disposition` column with the old labels in
-- it, or the old CHECK constraint). If you're setting this up for the
-- first time, just run add_disposition_to_stock_movements.sql instead —
-- it already uses the new labels, so this file is unnecessary.
--
-- This does three things, in order:
--   1. Drops the old CHECK constraint (if present) — otherwise the
--      rename below would be rejected by the constraint it's updating.
--   2. Renames any rows already marked with the old labels.
--   3. Re-adds the CHECK constraint with the new allowed values.
--
-- SAFE TO RE-RUN: every step here is guarded (IF EXISTS / only touches
-- matching rows / IF NOT EXISTS), so running this more than once, or
-- running it on a database that was never on the old labels, does
-- nothing harmful either way.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Inventory page — any back orders you'd already marked
--      now show "Reimbursed" / "Replaced" instead of the old labels.
-- =============================================================

ALTER TABLE stock_movements
    DROP CONSTRAINT IF EXISTS stock_movements_disposition_check;

UPDATE stock_movements SET disposition = 'Reimbursed' WHERE disposition = 'Refurbished';
UPDATE stock_movements SET disposition = 'Replaced'   WHERE disposition = 'Returned';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'stock_movements_disposition_check'
    ) THEN
        ALTER TABLE stock_movements
            ADD CONSTRAINT stock_movements_disposition_check
            CHECK (disposition IS NULL OR disposition IN ('Reimbursed', 'Replaced'));
    END IF;
END $$;
