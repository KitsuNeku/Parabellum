-- =============================================================
-- Parabellum ISOS — DEMO training data for MLR forecasting
-- Generated from paper delivery receipts (High Point Aluminum
-- and Glass Supply → Parabellum), transcribed into
-- parabellum_receipts.csv, then filtered to standard-hardware
-- SKUs only.
--
-- IMPORTANT — READ BEFORE RUNNING:
--
--   * This is DEMO data for showing the ML pipeline works
--     end-to-end. It is NOT enough data to produce trustworthy
--     forecasts. Only 2 distinct months are represented
--     (2024-03 and 2026-01), and most SKUs appear on only one
--     of those months. Per-material MLR will fall back to the
--     pooled model for every material with < 12 months of
--     history (i.e. all of them).
--
--   * These are PURCHASES from your supplier, not sales to
--     your customers. We are using them as a demand proxy
--     (per your explicit request). Coefficients the MLR
--     learns will reflect 'when Parabellum buys' rather than
--     'when Parabellum's customers order'.
--
--   * Several unit prices were inferred from line totals
--     because the handwritten unit price on the paper did not
--     reconcile (see parabellum_receipts.csv notes column).
--
--   * Receipt #8889 has ~PHP 20,485 worth of line items hidden
--     behind a post-it note in the original photo. Those items
--     are NOT in this SQL.
--
--   * Receipt #5833's date reads '01-24-24' but is treated as
--     2026-01-24 here (receipt numbers 5833 and 5856 are only
--     23 apart, and 5856 is confirmed 2026-01-27). If the
--     client confirms it's actually 2024, change these rows.
--
-- HOW TO USE:
--   1. Open Supabase SQL Editor.
--   2. Paste this entire file and click Run.
--   3. From your Flask app, POST /api/aggregate to rebuild
--      monthly_demand, then POST /api/forecast to retrain.
--   4. Look at the response's 'sample_size_warning' fields --
--      every material will have it, which is correct for this
--      volume of data. That's the honest signal, don't hide it.
--
-- IDEMPOTENT: uses ON CONFLICT DO NOTHING for materials and
-- does NOT delete existing stock_movements, so re-running this
-- script will INSERT DUPLICATE movements. If you need to
-- reset, run:
--   DELETE FROM stock_movements WHERE remarks LIKE 'DEMO:%';
-- before re-running.
-- =============================================================

BEGIN;

-- ---- 1) Materials -----------------------------------------
INSERT INTO materials
  (material_code, material_name, unit, unit_cost,
   current_stock, reorder_level, category, supplier)
VALUES
  ('MAT-DSILL', 'D-Sill', 'pc', 794.5, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-DHEAD', 'D-Head', 'pc', 688.5, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-TOPBOT', 'Top/Bottom', 'pc', 463.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SDBC', 'SDBC', 'pc', 396.5, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-3X7BRONZE', '3x7 Bronze', 'pc', 756.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-CHANDLE-L', 'C. Handle L', 'pc', 52.5, 0, 7, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-JRUBBER', 'J-Rubber', 'kls', 90.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-BVINYL', 'B-Vinyl', 'kls', 90.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SEALANT', 'Sealant (Brown/W)', 'box', 2520.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-BRIVETS-4-4', 'B-Rivets 4-4', 'box', 210.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-4X7BRONZE', '4x7 Bronze', 'pc', 1008.0, 0, 7, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SCREW-8X1', 'Screw 8x1', 'gros', 100.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-4KINDS-900S', '4 Kinds 900S', 'set', 6.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-PL12-13-900S', 'PL 12-13 900S', 'pc', 210.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SCREW-12X3', 'Screw 12x3', 'box', 700.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-4BAR-14-8', '4-bar 14 -8.0', 'set', 146.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-4BAR-8-5', '4-bar 8 -5.0', 'set', 106.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-PANEL-ASTRAGAL', 'Panel Astragal 900-WF', 'pc', 450.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-LOCKSTILE', 'Lockstile', 'pc', 465.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-INTERLOCKER', 'Interlocker', 'pc', 480.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SCREENPRONE-798W', 'Screen Prone 798-W', 'pc', 320.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-4BAR-1250', '4-bar 12.50', 'pc', 63.0, 0, 8, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-CHANDLE-R', 'C. Handle R', 'pc', 55.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-VINYL-3', 'Vinyl -3', 'kls', 90.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SCREW-8X2', 'Screw 8x2', 'grs', 150.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SCREW-6X34', 'Screw 6x3/4', 'grs', 70.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-TROLLER-S', 'T-Roller S', 'pc', 12.0, 0, 6, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply'),
  ('MAT-SCREENMESH-48W', 'Screen Mesh 48-W', 'box', 2400.0, 0, 5, 'Aluminum/Glass Hardware', 'High Point Aluminum and Glass Supply')
ON CONFLICT (material_code) DO NOTHING;

-- ---- 2) Stock movements (ISSUANCE = demand proxy) --------
-- Each row corresponds to one receipt line. movement_type is
-- ISSUANCE because that is what aggregate_monthly_demand() 
-- reads as 'demand_qty' — the training target for the MLR.

INSERT INTO stock_movements
  (material_id, movement_type, quantity, movement_date, remarks)
VALUES
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-3X7BRONZE'), 'ISSUANCE', 3, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''3x7 bronze'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4BAR-1250'), 'ISSUANCE', 39, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''4-bar 12.50'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BRIVETS-4-4'), 'ISSUANCE', 4, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''B-Rivets 4-4'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BVINYL'), 'ISSUANCE', 5, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''B-vinyl'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-CHANDLE-L'), 'ISSUANCE', 27, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''C. Handle L'' (W)'),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-CHANDLE-R'), 'ISSUANCE', 10, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''C. Handle R'' (W)'),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DHEAD'), 'ISSUANCE', 1, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''D-head'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DSILL'), 'ISSUANCE', 1, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''D-sill'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-INTERLOCKER'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Interlocker'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-JRUBBER'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''J-Rubber'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-LOCKSTILE'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Lockstile'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREENMESH-48W'), 'ISSUANCE', 1, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Screen mesh (48)-W'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREENPRONE-798W'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Screen prone 798-W'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-6X34'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Screw 6x3/4'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-8X2'), 'ISSUANCE', 3, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Screw 8x2'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SDBC'), 'ISSUANCE', 10, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''SDBC'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SEALANT'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Sealant W'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-TOPBOT'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Top/Bottom'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-TROLLER-S'), 'ISSUANCE', 30, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''T-roller S'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-VINYL-3'), 'ISSUANCE', 2, '2024-03-23', 'DEMO: purchase receipt #8889 treated as demand proxy — original desc ''Vinyl -3'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-3X7BRONZE'), 'ISSUANCE', 20, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''3x7 bronze'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4BAR-14-8'), 'ISSUANCE', 25, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''4-bar 14 -8.0'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4BAR-8-5'), 'ISSUANCE', 4, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''4 bar 8 -5.0'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4KINDS-900S'), 'ISSUANCE', 8, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''4 kinds 900S'' (HA)'),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4X7BRONZE'), 'ISSUANCE', 35, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''4x7 bronze'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BRIVETS-4-4'), 'ISSUANCE', 2, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''B-Rivets 4-4'' (HA)'),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BVINYL'), 'ISSUANCE', 2, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''B-Vinyl'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-CHANDLE-L'), 'ISSUANCE', 10, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''Com. Handle (L)'' (HA)'),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DHEAD'), 'ISSUANCE', 2, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''D-head 798-WF'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DSILL'), 'ISSUANCE', 2, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''D-sill 798-WF'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-JRUBBER'), 'ISSUANCE', 2, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''J-Rubber 900S'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-PANEL-ASTRAGAL'), 'ISSUANCE', 1, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''Panel Astragal 900-WF'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-PL12-13-900S'), 'ISSUANCE', 4, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''PL # 12-13 900S'' (HA)'),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-12X3'), 'ISSUANCE', 1, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''Screw 12x3'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-8X1'), 'ISSUANCE', 3, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''Screw 8x1'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SDBC'), 'ISSUANCE', 15, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''SDBC'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SEALANT'), 'ISSUANCE', 4, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''Sealant Brown 900S'''),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-TOPBOT'), 'ISSUANCE', 5, '2026-01-17', 'DEMO: purchase receipt #6172 treated as demand proxy — original desc ''Top/Bottom 798-WF''')
;

COMMIT;

-- After running, in your Flask app:
--   1. POST /api/aggregate  (rebuilds monthly_demand from these movements)
--   2. POST /api/forecast   (retrains MLR on the enriched data)