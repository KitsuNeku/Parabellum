-- =============================================================
-- Parabellum ISOS — Fix unrealistic project budgets
-- =============================================================
-- seed_data.py originally generated project budgets between
-- PHP 400,000 and PHP 3,500,000 — reasonable for a large
-- infrastructure contractor, but wildly out of scale for a small
-- aluminum/glass fabrication shop doing jobs like gates, fences,
-- handrails, and structural steel work for local customers.
--
-- This script re-randomizes the budget of EVERY EXISTING project
-- to a realistic PHP 8,000–60,000 range (capped at 60,000 as
-- requested). It does NOT touch any other column — project names,
-- customers, staff, status, progress, and dates are all left as-is.
--
-- random() is evaluated PER ROW by Postgres in an UPDATE, so every
-- project gets its own independent random value, not one value
-- copied to every row.
--
-- SAFE TO RE-RUN: each run just re-randomizes budgets again within
-- the same realistic range. There's no data loss risk — this only
-- touches the `budget` column.
--
-- HOW TO USE:
--   1. Open Supabase → SQL Editor → New Query.
--   2. Paste this entire file and click Run.
--   3. Reload the Projects page — budgets should now show values
--      like PHP 12,450 or PHP 47,900 instead of PHP 1,200,000+.
-- =============================================================

UPDATE projects
SET budget = round((random() * (60000 - 8000) + 8000)::numeric, 2);

-- Optional sanity check — run this separately to confirm the fix:
-- SELECT project_code, project_name, budget FROM projects ORDER BY budget DESC LIMIT 10;
