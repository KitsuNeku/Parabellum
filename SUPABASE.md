# Connecting Parabellum to Supabase

Supabase is just managed PostgreSQL with a dashboard on top. Since this
project already talks to a plain PostgreSQL database through `psycopg2`,
moving to Supabase is a **configuration change, not a code change** — you
only need to fill in different connection details.

---

## 1. Create the Supabase project

1. Go to https://supabase.com and sign in (GitHub login is fastest).
2. **New Project** → give it a name (e.g. `parabellum-isos`) → pick a
   region close to you → set a **database password** (write this down,
   you'll need it below) → **Create new project**.
3. Wait 1–2 minutes for it to finish provisioning.

---

## 2. Get your connection details

Supabase moved this recently — it's **not** under Settings anymore.

1. Go to your project's **main dashboard page** (the Home icon in the left
   sidebar, not Settings).
2. Click **Connect** — it's a button near the top of that page.
3. A panel opens with several connection options. Use **Session pooler**,
   not "Direct connection" — direct connections now require IPv6, which
   most home routers don't support, and you'll get a silent connection
   failure. The pooler works over ordinary IPv4.

You'll see something like this:

```
Host:     aws-<region>.pooler.supabase.com
Port:     5432
Database: postgres
User:     postgres.<your-project-ref>
```

That `<your-project-ref>` is the random string in your project's URL and
on the General Settings page as "Project ID" (e.g. `oclhphxleagpdjfiifku`).
**The username is the whole thing together** — `postgres.oclhphxleagpdjfiifku`,
not just `postgres`. This trips people up because every other Postgres
tool just uses `postgres` alone.

| Supabase calls it | Goes into `config.py` as |
|---|---|
| Host | `DB_HOST` |
| Port | `DB_PORT` (`5432` for the session pooler) |
| Database name | `DB_NAME` (`postgres`) |
| User | `DB_USER` (the full `postgres.xxxxxxxx` string) |
| Password | `DB_PASSWORD` (set when you created the project) |

**Forgot your database password?** It's not your Supabase login password —
it's a separate one set at project creation. Reset it from the **Connect**
panel, or Project Settings → **Database** if your dashboard still shows
that page.

---

## 3. Point config.py at Supabase

Open `config.py` and either:

**Option A — quick and easy:** edit the fallback values directly:

```python
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "aws-1-ap-southeast-1.pooler.supabase.com"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "postgres"),
    "user":     os.getenv("DB_USER", "postgres.oclhphxleagpdjfiifku"),  # full string, not just "postgres"
    "password": os.getenv("DB_PASSWORD", "the-password-you-set"),
    "sslmode":  os.getenv("DB_SSLMODE", "prefer"),
}
```

**Option B — safer (recommended if you'll push to GitHub):** leave
`config.py` untouched and set environment variables instead, so the
password never sits in a file at all:

```
set DB_HOST=aws-1-ap-southeast-1.pooler.supabase.com
set DB_PORT=5432
set DB_NAME=postgres
set DB_USER=postgres.oclhphxleagpdjfiifku
set DB_PASSWORD=the-password-you-set
```

(Windows `set` only lasts for that terminal session — for something more
permanent, add them under **System Properties → Environment Variables**.)

You don't need to touch `sslmode` — it's already set to `"prefer"`,
which uses an encrypted connection automatically since Supabase requires
one, and safely falls back to a plain connection on your local Postgres
if you ever switch back.

---

## 4. Create the tables

You have two options — same `schema.sql` file either way:

**Option A — Supabase's own SQL editor (no pgAdmin needed):**
In your Supabase project → **SQL Editor** (left sidebar) → **New query**
→ paste the entire contents of `schema.sql` → **Run**.

**Option B — keep using pgAdmin:**
pgAdmin can manage a remote Supabase database just like a local one.
Right-click **Servers** → **Register** → **Server…**, then under the
**Connection** tab enter the same host/port/user/password from step 2
(set **Maintain database** to `postgres`, and remember the username is
the full `postgres.xxxxxxxx` string, not just `postgres`). Once
connected, use **Query Tool** exactly as before and run `schema.sql`.

---

## 5. Seed it

From your project folder, same commands as always — they'll now write to
Supabase instead of your local machine:

```
python seed_users.py
python seed_data.py
```

---

## 6. Run the app

```
python app.py
```

Nothing else changes. `http://127.0.0.1:5000` still runs the Flask app
on your machine — only the *database* now lives on Supabase.

---

## Why this matters for your defense

- **Anyone can now run the app against the same live data** — no more
  "it works on my PC but not my groupmate's" because everyone was
  pointing at their own separate local database.
- **The database survives even if your laptop doesn't** — useful if your
  PC has issues on defense day.
- You can also open the **Table Editor** in the Supabase dashboard to
  show panelists your actual data live, without opening pgAdmin.

---

## Troubleshooting

**Connection just hangs, or "connection refused" with no clear reason**
- You're probably using the **Direct connection** details instead of the
  **Session pooler**. Direct connections need IPv6, which most home
  routers don't have. Go back to the **Connect** button and copy the
  Session pooler details instead — the host will contain `pooler.supabase.com`.

**`password authentication failed`**
- Check the username first — it must be the full `postgres.xxxxxxxx`
  form for the pooler, not just `postgres`. That's the single most common
  mistake here.
- If the username is right, this is the *database* password you set when
  creating the project — not your Supabase account login password. Reset
  it from the **Connect** panel if you've forgotten it.

**`could not translate host name`**
- Copy the host directly from the Connect panel rather than typing it —
  it's easy to mistype the region code (e.g. `ap-southeast-1`).

**Connection works but is slow, or you hit "too many connections"**
- This app opens a new database connection for every request rather than
  reusing one. That's fine for a handful of users during your defense.
  If you need more headroom, the **Connect** panel also offers a
  **Transaction pooler** option (port `6543`) built for exactly this.

**Still using your local database and just want to switch back?**
Just change `config.py` (or your environment variables) back to
`localhost` with the plain `postgres` username — nothing else in the
project needs to change either way.
