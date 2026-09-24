-- =============================================================
-- Parabellum ISOS — Fix unrealistic transaction totals
-- =============================================================
-- seed_data.py originally picked transaction quantity independently
-- of the material's unit price (5-120 units, regardless of whether
-- the material was a PHP 190 flat bar or an PHP 8,900 H-Beam). That
-- let a single transaction's VAT-inclusive total (quantity x
-- unit_price x 1.12, which is what the UI displays) run into the
-- hundreds of thousands or more — wildly unrealistic for a small
-- fabrication shop's day-to-day material purchases.
--
-- This script recalculates quantity (and the matching `amount`
-- column, which the dashboard/reports read separately from the
-- transactions list) ONLY for transactions whose total currently
-- EXCEEDS PHP 50,000. Each affected row's real unit_price is kept
-- exactly as-is; only the quantity is scaled down to a realistic
-- purchase size for that material, targeting a fresh random total
-- between roughly PHP 560 and PHP 49,280 (post-VAT).
--
-- Transactions already under the PHP 50,000 cap are left completely
-- untouched — this only corrects the ones that are actually broken.
--
-- SAFE TO RE-RUN: rows that are already under the cap are excluded
-- by the WHERE clause every time, so re-running this after it's
-- already fixed everything is a no-op.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Client Transactions page — every row's Total
--      column should now show PHP 50,000 or less.
-- =============================================================

WITH recalced AS (
    SELECT transaction_id,
           unit_price,
           -- random() always returns double precision in Postgres, and
           -- the two-argument ROUND(value, decimals) only has an
           -- overload for numeric - NOT double precision. Casting right
           -- after random() keeps everything numeric from here on,
           -- avoiding "function round(double precision, integer) does
           -- not exist".
           GREATEST(1::numeric, LEAST(
               ROUND((random() * (44000 - 500) + 500)::numeric / NULLIF(unit_price, 0)),
               FLOOR(50000::numeric / NULLIF(unit_price * 1.12, 0))
           )) AS new_qty
    FROM transactions
    WHERE quantity * unit_price * 1.12 > 50000
)
UPDATE transactions
SET quantity = recalced.new_qty,
    amount   = ROUND((recalced.new_qty * recalced.unit_price)::numeric, 2)
FROM recalced
WHERE transactions.transaction_id = recalced.transaction_id;

-- Optional sanity check — run this separately to confirm the fix:
-- SELECT transaction_id, material_name, quantity, unit_price,
--        ROUND(quantity * unit_price * 1.12, 2) AS total_incl_vat
--   FROM transactions
--   ORDER BY total_incl_vat DESC
--   LIMIT 10;
