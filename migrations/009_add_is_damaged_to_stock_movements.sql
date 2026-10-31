-- =============================================================
-- Parabellum ISOS — Damaged returns don't restock
-- =============================================================
-- Record Return previously always added the returned quantity back to
-- current_stock, treating every return as sellable. That's wrong for a
-- return that came back damaged - it was logged, but it should NOT have
-- increased on-hand stock. This adds a column so the Record Return modal
-- can say which one it was, and the backend only restocks the good ones.
--
-- SAFE TO RE-RUN: ADD COLUMN IF NOT EXISTS makes this idempotent.
-- Existing RETURN rows are untouched and default to is_damaged = FALSE
-- (i.e. "already counted as restocked, same as before this migration"),
-- so current_stock is NOT recalculated by this script - nothing you've
-- already recorded changes. This only affects returns recorded AFTER the
-- migration runs and you start actually picking "Damaged" in the modal.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Inventory page - the Record Return modal now has a
--      Condition field (Good / Damaged).
-- =============================================================

ALTER TABLE stock_movements
    ADD COLUMN IF NOT EXISTS is_damaged BOOLEAN NOT NULL DEFAULT FALSE;
