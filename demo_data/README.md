# Demo training data — three variants, one CSV

You have three different ways to load data into the ISOS DB, plus one
CSV that documents what's in each. **Pick ONE of the three SQL loaders**
— they insert the same underlying data along different paths and would
double-count if combined.

## Installation

Drop this whole folder into your existing project as
`Parabellum/demo_data/`, then run the appropriate SQL in Supabase's
SQL Editor.

## The three loaders, ranked by what you want

### 1. `parabellum_blended_3yr.sql` — for a defense presentation

- **1,036 rows** across **37 months** (Jan 2023 → Jan 2026), 28 materials.
- **38 rows are REAL** (from the client's paper receipts, preserved at
  their exact observed months: 2024-03 and 2026-01).
- **998 rows are SYNTHETIC**, generated from a documented demand model
  (seasonal factor + weather sensitivity + growth trend + serial
  correlation + noise). The synthetic values flow naturally through the
  real anchors so the series looks coherent.
- `parabellum_blended_3yr_provenance.csv` lists every single row and
  which category (`real` or `synthetic`) it came from — the audit trail.
- **YOU MUST BE HONEST ABOUT THE BLEND** at the defense. Defensible
  phrasing is in the SQL file's header comment. Presenting this as "3
  years of Parabellum's actual history" would be data fabrication.
- Enough data for the per-material MLR with lag features to actually
  train (37 months per material, well above the 15-month threshold).

### 2. `parabellum_training_only.sql` — leanest form of just the real data

- **38 rows** — same real receipt-derived data as the blend, but nothing
  synthetic. Writes directly into `monthly_demand` (no receipt-number
  provenance in the DB).
- Model will train (38 rows > threshold) but lag features and
  per-material fits will auto-fall-back due to thin data. Predictions
  will be roughly seasonal averages.
- Use if you want "real data only, no synthetic backfill."

### 3. `parabellum_training_demo.sql` — audit-trail version of #2

- Same 38 real rows, but written into `stock_movements` with receipt
  numbers preserved in the `remarks` column. Requires
  `POST /api/aggregate` after loading to build `monthly_demand`.
- Use if you need each row in the DB to be traceable to a specific
  paper receipt.

## The CSVs

- **`parabellum_receipts.csv`** — the original 91-row transcription of
  all 8 delivery-receipt photos, including custom-cut glass items (which
  don't get loaded by any of the SQL files because they can't repeat).
  Includes per-row reading confidence, arithmetic checks, and notes.
  Read this if you want to see exactly what was on the paper.

- **`parabellum_blended_3yr_provenance.csv`** — pairs with loader #1.
  Every (material, month, quantity) row plus its `source` column marking
  it `real` or `synthetic`. This is your audit answer for anyone who asks
  "where did that number come from?"

## Utility scripts (unrelated to MLR training data)

### `fix_project_budgets.sql`

`seed_data.py` originally generated project budgets between PHP
400,000 and 3,500,000 — reasonable for a large contractor, not for a
small aluminum/glass fabrication shop. This script re-randomizes every
existing project's `budget` to a realistic PHP 8,000–60,000 range, done
server-side in Postgres so it works regardless of how many projects
exist or what their current values are. Safe to re-run — it only
touches the `budget` column. `seed_data.py` itself has also been fixed
so any future re-seed already generates realistic values from the start.

### `fix_transaction_totals.sql`

Same class of problem, different table: `seed_data.py` picked each
transaction's quantity independently of the material's real unit
price, so a big-ticket material (e.g. an PHP 8,900 H-Beam) times a
random 5–120 unit quantity could produce a VAT-inclusive total in the
hundreds of thousands. This script recalculates `quantity` (and the
matching `amount` column) ONLY for transactions whose total currently
exceeds PHP 50,000, scaling quantity down to a realistic purchase size
for that material's real unit price — transactions already under the
cap are left untouched. `seed_data.py` has also been fixed so future
transactions are generated from a realistic target-total range instead
of an independent random quantity.

### `add_recorded_by_column.sql`

Adds a `recorded_by` column to the existing `stock_movements` table so
the Inventory page's Stock In / Stock Out tables can show which
logged-in user performed each movement. **Run this once** if your
database was created before this feature existed — otherwise new
Stock In / Stock Out actions will fail to record (or the column simply
won't exist yet). Existing historical movements will show "—" for
Recorded By, since there's no way to know retroactively who performed
them; every new movement from this point on captures it automatically.

## Operational notes

- **Only run ONE** of the three SQL files.
- Loaders #1 and #2 write directly to `monthly_demand`. Do NOT hit
  `POST /api/aggregate` after either of them — that endpoint TRUNCATEs
  `monthly_demand` and rebuilds it from `stock_movements`, erasing
  everything. Only hit `POST /api/forecast`.
- **If you've enabled automatic nightly retraining** (see
  `config.AUTO_RETRAIN_ENABLED`), the same rule applies to
  `config.AUTO_AGGREGATE_BEFORE_RETRAIN`: leave it at its default
  (`0`/off) while you're using any of these demo loaders, or the
  nightly job will silently wipe this data the same way a manual
  `/api/aggregate` call would. It's safe to leave the nightly retrain
  itself ON — it only re-runs `run_forecast`, which reads
  `monthly_demand` without modifying it.
- Loader #3 writes to `stock_movements`. You DO need
  `POST /api/aggregate` after it, to build the monthly panel.
- For loader #1 (blended 3-year), also run
  `python weather_api.py 2023-01-01` from `Parabellum/` so
  `monthly_weather` has real Lipa City weather covering the same
  3-year span. Without this, the weather feature falls back to zero and
  the model trains without real weather signal.
