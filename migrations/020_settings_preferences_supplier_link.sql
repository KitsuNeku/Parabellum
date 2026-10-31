CREATE TABLE IF NOT EXISTS company_settings (
    id           INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    company_name VARCHAR(150) NOT NULL DEFAULT 'Parabellum Steel & Iron Works',
    tin          VARCHAR(30),
    email        VARCHAR(150),
    phone        VARCHAR(40),
    address      VARCHAR(250),
    currency     VARCHAR(10)  NOT NULL DEFAULT 'PHP',
    vat_rate     NUMERIC(5,2) NOT NULL DEFAULT 12 CHECK (vat_rate >= 0 AND vat_rate <= 100),
    updated_at   TIMESTAMPTZ  DEFAULT CURRENT_TIMESTAMP,
    updated_by   VARCHAR(60)
);
INSERT INTO company_settings (id, company_name, email, address)
VALUES (1, 'Parabellum Steel & Iron Works', 'info@parabellumsteel.ph', 'Lipa City, Batangas, Philippines')
ON CONFLICT (id) DO NOTHING;

ALTER TABLE users ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE materials ADD COLUMN IF NOT EXISTS supplier_id INT REFERENCES suppliers(supplier_id) ON DELETE SET NULL;
UPDATE materials m
   SET supplier_id = s.supplier_id
  FROM suppliers s
 WHERE m.supplier_id IS NULL
   AND LOWER(TRIM(m.supplier)) = LOWER(TRIM(s.name));
