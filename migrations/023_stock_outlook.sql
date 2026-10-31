ALTER TABLE materials ADD COLUMN IF NOT EXISTS critical_level NUMERIC(12,2) NOT NULL DEFAULT 0;

ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS delivery_attempts INT NOT NULL DEFAULT 0;
ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS returned_at TIMESTAMPTZ;
ALTER TABLE stock_movements ADD COLUMN IF NOT EXISTS returned_by VARCHAR(80);

CREATE TABLE IF NOT EXISTS delivery_attempts (
    attempt_id   SERIAL PRIMARY KEY,
    movement_id  INT NOT NULL REFERENCES stock_movements(movement_id) ON DELETE CASCADE,
    outcome      VARCHAR(12) NOT NULL CHECK (outcome IN ('Delivered', 'Failed')),
    reason       TEXT,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    temp_c       NUMERIC(5,2),
    rainfall_mm  NUMERIC(8,2),
    wind_kmh     NUMERIC(6,2),
    recorded_by  VARCHAR(80)
);
CREATE INDEX IF NOT EXISTS idx_delivery_attempts_movement ON delivery_attempts (movement_id);

INSERT INTO delivery_attempts (movement_id, outcome, reason, attempted_at, temp_c, rainfall_mm, wind_kmh)
SELECT sm.movement_id,
       CASE WHEN sm.delivered_at IS NOT NULL THEN 'Delivered' ELSE 'Failed' END,
       CASE WHEN sm.delivered_at IS NOT NULL THEN NULL ELSE sm.delivery_failure_reason END,
       COALESCE(sm.delivered_at, sm.delivery_failed_at),
       sm.delivery_temp_c, sm.delivery_rainfall_mm, sm.delivery_wind_kmh
  FROM stock_movements sm
 WHERE (sm.delivered_at IS NOT NULL OR sm.delivery_failed_at IS NOT NULL)
   AND NOT EXISTS (SELECT 1 FROM delivery_attempts a WHERE a.movement_id = sm.movement_id);

UPDATE stock_movements sm
   SET delivery_attempts = (SELECT COUNT(*) FROM delivery_attempts a WHERE a.movement_id = sm.movement_id)
 WHERE delivery_attempts = 0
   AND (delivered_at IS NOT NULL OR delivery_failed_at IS NOT NULL);

UPDATE role_permissions SET permissions = permissions || ',outlook'
 WHERE role IN ('System Administrator', 'Inventory Personnel', 'Management/Owner')
   AND (',' || permissions || ',') NOT LIKE '%,outlook,%';
