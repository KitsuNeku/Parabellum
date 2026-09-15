-- =============================================================
-- Parabellum ISOS — TRAINING-ONLY data (minimal, no audit trail)
--
-- Writes directly into monthly_demand -- the aggregated panel
-- that prepare_mlr_dataset() reads. Skips stock_movements and
-- the aggregate_monthly_demand() step entirely.
--
-- Use parabellum_training_demo.sql (in the same folder) instead
-- if you need to trace each row back to a specific receipt --
-- that version keeps the receipt-number provenance, this one
-- does not.
--
-- IMPORTANT -- READ BEFORE RUNNING:
--
--   * DO NOT run POST /api/aggregate after this. That endpoint
--     TRUNCATEs monthly_demand and rebuilds from stock_movements
--     (which won't have these rows), erasing this data.
--     Only run POST /api/forecast.
--
--   * Same volume limitation as the demo variant: 38
--     (material, month) rows across 2 distinct months. The MLR
--     will train (pipeline runs end-to-end) but won't learn
--     much from data this thin. See demo_data/README.md.
--
--   * Reset command (if you want to remove just these rows):
--       DELETE FROM monthly_demand
--        WHERE material_id IN (SELECT material_id FROM materials
--          WHERE material_code LIKE 'MAT-%');
-- =============================================================

BEGIN;

-- Materials (same as parabellum_training_demo.sql; idempotent)
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

-- monthly_demand: the exact rows the MLR will train on.
-- All non-demand columns default to 0 (inventory_balance,
-- inventory_value, transaction_volume, active_projects) --
-- the current per-material MLR doesn't use them, so zeros are
-- fine for training. If you later use a model variant that does,
-- backfill these columns first.
INSERT INTO monthly_demand
  (material_id, period_month, demand_qty)
VALUES
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-3X7BRONZE'), '2024-03-01', 3.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-3X7BRONZE'), '2026-01-01', 20.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4BAR-1250'), '2024-03-01', 39.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4BAR-14-8'), '2026-01-01', 25.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4BAR-8-5'), '2026-01-01', 4.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4KINDS-900S'), '2026-01-01', 8.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-4X7BRONZE'), '2026-01-01', 35.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BRIVETS-4-4'), '2024-03-01', 4.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BRIVETS-4-4'), '2026-01-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BVINYL'), '2024-03-01', 5.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-BVINYL'), '2026-01-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-CHANDLE-L'), '2024-03-01', 27.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-CHANDLE-L'), '2026-01-01', 10.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-CHANDLE-R'), '2024-03-01', 10.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DHEAD'), '2024-03-01', 1.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DHEAD'), '2026-01-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DSILL'), '2024-03-01', 1.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-DSILL'), '2026-01-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-INTERLOCKER'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-JRUBBER'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-JRUBBER'), '2026-01-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-LOCKSTILE'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-PANEL-ASTRAGAL'), '2026-01-01', 1.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-PL12-13-900S'), '2026-01-01', 4.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREENMESH-48W'), '2024-03-01', 1.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREENPRONE-798W'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-12X3'), '2026-01-01', 1.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-6X34'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-8X1'), '2026-01-01', 3.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SCREW-8X2'), '2024-03-01', 3.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SDBC'), '2024-03-01', 10.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SDBC'), '2026-01-01', 15.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SEALANT'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-SEALANT'), '2026-01-01', 4.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-TOPBOT'), '2024-03-01', 2.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-TOPBOT'), '2026-01-01', 5.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-TROLLER-S'), '2024-03-01', 30.0),
  ((SELECT material_id FROM materials WHERE material_code = 'MAT-VINYL-3'), '2024-03-01', 2.0)
ON CONFLICT (material_id, period_month) DO UPDATE SET
  demand_qty = EXCLUDED.demand_qty;

COMMIT;

-- After running, in your Flask app: hit POST /api/forecast ONLY.
-- Do NOT hit /api/aggregate -- that would wipe these rows.