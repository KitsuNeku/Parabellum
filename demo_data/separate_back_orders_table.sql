-- =============================================================
-- Parabellum ISOS — Give Back Orders their own table
-- =============================================================
-- Back orders (movement_type = 'RETURN') used to live as rows inside
-- stock_movements, mixed in with real Stock In / Stock Out records.
-- They now get a dedicated back_orders table of their own.
--
-- This also changes what a disposition means: marking a back order
-- "Replaced" now ADDS its quantity back into materials.current_stock
-- (the item physically goes back on the shelf, since the customer was
-- given their money back instead and the returned unit is fine to
-- resell). "Reimbursed" does NOT add to stock (the customer kept the
-- replacement; this unit is written off). Previously, neither
-- disposition touched stock.
--
-- This single script is safe to run whether or not you already ran an
-- earlier version of it (one that had the two the other way around):
--   1. Create back_orders (idempotent - IF NOT EXISTS).
--   2. Copy any RETURN rows still in stock_movements into it (a no-op
--      if you already ran this and they're gone).
--   3. Make materials.current_stock match the CURRENT rule exactly:
--      add stock for any "Replaced" row not yet marked restocked, and
--      remove stock from any row that IS marked restocked but is no
--      longer "Replaced" (undoing an earlier run's now-wrong add) -
--      each row's quantity is only ever added or removed once either
--      way, tracked by its own `restocked` flag.
--   4. Delete the migrated RETURN rows from stock_movements (a no-op if
--      already gone), then tighten its CHECK constraint to match
--      (RECEIPT/ISSUANCE only).
--
-- SAFE TO RE-RUN at any time, in any state - every step is guarded
-- (IF EXISTS / only touches rows not yet in the new, correct state).
--
-- HOW TO USE: Supabase → SQL Editor → New Query → paste this whole file
-- → Run. Then restart the app (or just reload the Inventory page).
-- =============================================================

CREATE TABLE IF NOT EXISTS back_orders (
    back_order_id SERIAL PRIMARY KEY,
    material_id   INT NOT NULL REFERENCES materials(material_id),
    quantity      NUMERIC(12,2) NOT NULL CHECK (quantity > 0),
    return_date   DATE NOT NULL,
    stock_out_ref VARCHAR(120),
    remarks       TEXT,
    back_order_by VARCHAR(120),
    recorded_by   VARCHAR(80),
    disposition   VARCHAR(20)
                  CHECK (disposition IS NULL OR disposition IN ('Reimbursed', 'Replaced')),
    restocked     BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS idx_back_order_material_date
    ON back_orders (material_id, return_date);

INSERT INTO back_orders (material_id, quantity, return_date, remarks, back_order_by, recorded_by, disposition, restocked)
SELECT sm.material_id, sm.quantity, sm.movement_date, sm.remarks, sm.back_order_by, sm.recorded_by,
       sm.disposition, FALSE
  FROM stock_movements sm
 WHERE sm.movement_type = 'RETURN'
   AND NOT EXISTS (
       SELECT 1 FROM back_orders bo
        WHERE bo.material_id = sm.material_id AND bo.return_date = sm.movement_date
          AND bo.quantity = sm.quantity AND COALESCE(bo.recorded_by, '') = COALESCE(sm.recorded_by, '')
   );

-- Add stock for anything that should now be restocked ("Replaced") but
-- isn't yet - covers both a brand-new migration and a first-time
-- application of the "Replaced restocks" rule.
UPDATE materials m
   SET current_stock = current_stock + bo.quantity
  FROM back_orders bo
 WHERE bo.material_id = m.material_id
   AND bo.disposition = 'Replaced'
   AND bo.restocked = FALSE;

UPDATE back_orders SET restocked = TRUE
 WHERE disposition = 'Replaced' AND restocked = FALSE;

-- Undo any restock that no longer matches the rule - covers re-running
-- this after an earlier version of the script applied it to the wrong
-- disposition (back when "Reimbursed" restocked instead of "Replaced").
UPDATE materials m
   SET current_stock = GREATEST(0, current_stock - bo.quantity)
  FROM back_orders bo
 WHERE bo.material_id = m.material_id
   AND bo.restocked = TRUE
   AND (bo.disposition IS DISTINCT FROM 'Replaced');

UPDATE back_orders SET restocked = FALSE
 WHERE restocked = TRUE AND disposition IS DISTINCT FROM 'Replaced';

DELETE FROM stock_movements WHERE movement_type = 'RETURN';

ALTER TABLE stock_movements DROP CONSTRAINT IF EXISTS stock_movements_movement_type_check;
ALTER TABLE stock_movements ADD CONSTRAINT stock_movements_movement_type_check
    CHECK (movement_type IN ('RECEIPT', 'ISSUANCE'));

ALTER TABLE stock_movements DROP COLUMN IF EXISTS back_order_by;
ALTER TABLE stock_movements DROP COLUMN IF EXISTS disposition;
ALTER TABLE stock_movements DROP COLUMN IF EXISTS is_damaged;
