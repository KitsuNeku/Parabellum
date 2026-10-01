-- =============================================================
-- Parabellum ISOS — Recalculate on-hand stock, excluding back orders
-- =============================================================
-- Record Return used to add its quantity into materials.current_stock
-- (same effect as a Stock In). That's been changed - a back order is now
-- logged for the record only and never touches current_stock (on-hand
-- "pcs" only ever reflects actual Stock In / Stock Out).
--
-- That code fix only affects returns recorded AFTER you deploy it. Any
-- return you already recorded under the OLD behavior already added its
-- quantity into current_stock, so your on-hand numbers may still be
-- inflated by past back orders. This ONE-TIME script recalculates every
-- material's current_stock from scratch, using only its RECEIPT and
-- ISSUANCE history (exactly matching the new rule) - so it will LOWER
-- the on-hand count for any material that has ever had a return recorded
-- against it.
--
-- SAFE-ISH TO RE-RUN, but it is NOT idempotent in the usual sense: it
-- recalculates every material every time you run it, from the full
-- stock_movements history. Running it twice in a row is harmless (same
-- result both times) - but running it is a real data change, not just a
-- missing-table/column fix like the other scripts in this folder, so
-- read this whole comment before running it.
--
-- Review BEFORE committing to the change - run the SELECT first:
--
--   SELECT m.material_code, m.material_name, m.current_stock AS old_stock,
--          COALESCE(SUM(CASE WHEN sm.movement_type = 'RECEIPT'  THEN sm.quantity
--                             WHEN sm.movement_type = 'ISSUANCE' THEN -sm.quantity
--                             ELSE 0 END), 0) AS new_stock
--   FROM materials m
--   LEFT JOIN stock_movements sm ON sm.material_id = m.material_id
--   GROUP BY m.material_id, m.material_code, m.material_name, m.current_stock
--   HAVING m.current_stock != COALESCE(SUM(CASE WHEN sm.movement_type = 'RECEIPT'  THEN sm.quantity
--                                              WHEN sm.movement_type = 'ISSUANCE' THEN -sm.quantity
--                                              ELSE 0 END), 0)
--   ORDER BY m.material_code;
--
-- Only materials with a mismatch show up - if that's empty, nothing to
-- fix and you don't need to run the UPDATE below at all.
--
-- HOW TO USE:
--   1. Run the SELECT above first and check the old_stock/new_stock
--      columns make sense for your data.
--   2. Open Supabase → SQL Editor → New Query.
--   3. Paste and run the UPDATE below.
--   4. Reload the Inventory page / Dashboard.
-- =============================================================

UPDATE materials m
SET current_stock = sub.new_stock
FROM (
    SELECT m2.material_id,
           COALESCE(SUM(CASE WHEN sm.movement_type = 'RECEIPT'  THEN sm.quantity
                              WHEN sm.movement_type = 'ISSUANCE' THEN -sm.quantity
                              ELSE 0 END), 0) AS new_stock
    FROM materials m2
    LEFT JOIN stock_movements sm ON sm.material_id = m2.material_id
    GROUP BY m2.material_id
) sub
WHERE m.material_id = sub.material_id;
