-- =============================================================
-- Parabellum ISOS - Delivery confirmation on Stock Out  (TEMPORARY)
-- =============================================================
-- Adds the columns behind the "Mark as Delivered" and "Mark as Failed"
-- buttons. Run ONCE on your EXISTING database (Supabase: SQL Editor >
-- paste > Run). Safe to run again - it skips columns that already exist.
-- Every existing Stock Out starts as Pending.
--
-- TO REVERT LATER:
--   ALTER TABLE stock_movements
--     DROP COLUMN IF EXISTS delivered_at,
--     DROP COLUMN IF EXISTS delivery_temp_c,
--     DROP COLUMN IF EXISTS delivery_rainfall_mm,
--     DROP COLUMN IF EXISTS delivery_wind_kmh,
--     DROP COLUMN IF EXISTS delivery_failed_at,
--     DROP COLUMN IF EXISTS delivery_failure_reason;
-- =============================================================

ALTER TABLE stock_movements
    ADD COLUMN IF NOT EXISTS delivered_at             TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS delivery_temp_c          NUMERIC(5,2),
    ADD COLUMN IF NOT EXISTS delivery_rainfall_mm     NUMERIC(8,2),
    ADD COLUMN IF NOT EXISTS delivery_wind_kmh        NUMERIC(6,2),
    ADD COLUMN IF NOT EXISTS delivery_failed_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS delivery_failure_reason  TEXT;
