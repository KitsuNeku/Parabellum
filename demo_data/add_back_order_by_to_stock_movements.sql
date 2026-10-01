-- =============================================================
-- Parabellum ISOS — Track who initiated a back order
-- =============================================================
-- Record Return already captured a "Customer / Project" value, but it was
-- only ever folded into the Remarks text (e.g. "Returned by M. Santos —
-- wrong size"). This adds a real column so the Back Orders table and the
-- back-order report can show who returned the material as its own field,
-- separate from Remarks (the reason) and Recorded By (the staff member
-- who entered it into the system).
--
-- SAFE TO RE-RUN: ADD COLUMN IF NOT EXISTS makes this idempotent.
-- Existing RETURN rows are untouched and get back_order_by = NULL (i.e.
-- "not recorded" for returns logged before this column existed) — nothing
-- you've already recorded changes, and current_stock is not affected at
-- all.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Inventory page — the Record Return modal's "Customer /
--      Project" field is now labeled "Back-Ordered By" and the Back
--      Orders table shows a dedicated "Back-Ordered By" column.
-- =============================================================

ALTER TABLE stock_movements
    ADD COLUMN IF NOT EXISTS back_order_by VARCHAR(120);
