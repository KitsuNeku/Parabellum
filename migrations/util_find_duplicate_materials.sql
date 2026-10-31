-- =============================================================
-- Parabellum ISOS — Find duplicate inventory items
-- =============================================================
-- READ-ONLY - this only SELECTs, it changes nothing. Safe to run any time.
--
-- Why this exists: the Stock In modal's "type a new item name" box (used
-- to register a brand-new item) didn't check whether an item with that
-- name already existed. If you typed a name that was a different case or
-- had extra spaces compared to an existing item - instead of picking that
-- item from the search dropdown - it silently created a second row for
-- the "same" item. From then on, Stock In/Out/Return actions could land
-- on either row depending on which one the search happened to match,
-- splitting one item's real stock across two rows with two different
-- quantities. (This has since been fixed - app.py now rejects creating a
-- new item whose name already matches one, case/spacing-insensitive - so
-- this script is for finding duplicates that were created before that fix.)
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Any item name printed here has more than one row. For each one,
--      decide which material_code to KEEP (usually the one with the
--      longer/more complete history), then ask your developer/Claude for
--      the merge steps - moving the other row's stock_movements onto the
--      kept item, recomputing its current_stock from that full movement
--      history, and deleting the now-empty duplicate row. Don't delete a
--      duplicate material row directly - its stock_movements rows would
--      be silently lost too (or blocked, since they reference it).
-- =============================================================

SELECT
    material_name,
    COUNT(*) AS duplicate_rows,
    STRING_AGG(
        material_code || ' — qty on hand: ' || current_stock || ', added ' || added_date,
        E'\n'
        ORDER BY material_id
    ) AS rows_found
FROM materials
GROUP BY LOWER(TRIM(material_name))
HAVING COUNT(*) > 1
ORDER BY material_name;
