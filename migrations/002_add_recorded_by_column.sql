-- =============================================================
-- Parabellum ISOS — Add "recorded by" tracking to stock movements
-- =============================================================
-- Adds a recorded_by column to the EXISTING stock_movements table so
-- the Stock In / Stock Out tables can show which logged-in user
-- performed each movement. Safe to run on your live database — this
-- does NOT touch schema.sql or drop/recreate anything.
--
-- Existing rows (movements recorded before this column existed) will
-- show "—" in the Recorded By column, since there's no way to know
-- retroactively who performed them. Every new Stock In / Stock Out
-- from now on will correctly capture the logged-in user's name.
--
-- SAFE TO RE-RUN: IF NOT EXISTS means running this twice does nothing
-- the second time.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Inventory page — new Stock In / Stock Out actions
--      will now show who performed them.
-- =============================================================

ALTER TABLE stock_movements
  ADD COLUMN IF NOT EXISTS recorded_by VARCHAR(80);
