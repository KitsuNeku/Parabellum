# Database migrations

`schema.sql` already contains every change below. A **new** database only
needs `schema.sql`, then `python seed_users.py` (and optionally a dataset
from `demo_data/`).

These files are for upgrading a database that was created with an older
`schema.sql`. Run them in number order in the Supabase SQL Editor (or
pgAdmin). Each one is safe to re-run.

`util_find_duplicate_materials.sql` is a read-only check, not a migration.
