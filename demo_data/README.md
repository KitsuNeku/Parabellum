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

## Operational notes

- **Only run ONE** of the three SQL files.
- Loaders #1 and #2 write directly to `monthly_demand`. Do NOT hit
  `POST /api/aggregate` after either of them — that endpoint TRUNCATEs
  `monthly_demand` and rebuilds it from `stock_movements`, erasing
  everything. Only hit `POST /api/forecast`.
- Loader #3 writes to `stock_movements`. You DO need
  `POST /api/aggregate` after it, to build the monthly panel.
- For loader #1 (blended 3-year), also run
  `python weather_api.py 2023-01-01` from `Parabellum/` so
  `monthly_weather` has real Lipa City weather covering the same
  3-year span. Without this, the weather feature falls back to zero and
  the model trains without real weather signal.
