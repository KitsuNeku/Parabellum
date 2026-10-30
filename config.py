"""
Database connection settings.
=================================================================
This is the ONLY place your database credentials should live.

These five values are what pgAdmin showed you under
  Servers > (your server) > Properties > Connection tab
plus the database name from the Databases tree.

Two ways to use this:

  EASY  : just edit the fallback values below to match your setup.
  SAFER : leave them alone and set environment variables instead
          (DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD).

IMPORTANT: your documentation lists GitHub in the dev environment.
Do NOT push your real password to GitHub. Either use the environment
variables, or add this file to .gitignore before you commit.
"""

import os
import secrets

DB_CONFIG = {
    # CONFIRM THIS: built from your Project ID + region (ap-southeast-1).
    # Supabase's pooler prefix is usually "aws-0-" or "aws-1-" - open your
    # Supabase dashboard → Connect → Session pooler and check the exact
    # host shown there matches this. If not, paste the real one in.
    "host":     os.getenv("DB_HOST", "aws-0-ap-southeast-1.pooler.supabase.com"),
    "port":     int(os.getenv("DB_PORT", 5432)),          # Session pooler port
    "dbname":   os.getenv("DB_NAME", "postgres"),          # confirmed: Supabase default
    "user":     os.getenv("DB_USER", "postgres.oclhphxleagpdjfiifku"),  # confirmed: your Project ID
    # YOU MUST CHANGE THIS - nobody but you has your database password.
    # It's the one you set when creating the Supabase project (not your
    # Supabase login password). Reset it from the Connect panel if lost.
    "password": os.getenv("DB_PASSWORD", "dimayuganeo13"),
    "sslmode":  os.getenv("DB_SSLMODE", "prefer"),
}

# Signs and encrypts the session cookie Flask hands out after login.
# If this changes, every logged-in user is signed out (their cookie no
# longer verifies) - that is intended behavior for a leaked/rotated key.
#
# For a class defense, the random fallback below is fine: it just means
# everyone gets logged out whenever the server restarts, which is not a
# real problem for local demoing.
#
# For anything closer to real deployment, set a FIXED value via the
# SECRET_KEY environment variable so sessions survive a restart, and
# never commit that value to GitHub (config.py is already.gitignored).
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))

# Only enable Flask's debug mode locally. Debug mode exposes an
# interactive in-browser Python console on error pages - anyone who can
# reach the server can execute code through it. It must never be on
# where the app is reachable by more than just your own machine.
#
# Defaults to OFF (production-safe). Enable locally with FLASK_DEBUG=1.
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

# =================================================================
# Automatic nightly retraining (see scheduler.py)
# =================================================================
# The MLR retrains itself once a day with no one needing to click
# "Generate Forecast" — same model, same math, same evaluation, just
# triggered on a timer instead of a button press.
#
# AUTO_RETRAIN_ENABLED: turn the whole feature off if you want purely
# manual control again (e.g. while debugging).
AUTO_RETRAIN_ENABLED = os.getenv("AUTO_RETRAIN_ENABLED", "1") == "1"

# AUTO_RETRAIN_HOUR: hour of day (0-23, in the SERVER's local time zone)
# the nightly retrain fires. Default 2 = 2:00 AM, when nobody's using
# the dashboard, so a several-second retrain is invisible to users.
AUTO_RETRAIN_HOUR = int(os.getenv("AUTO_RETRAIN_HOUR", "2"))

# AUTO_AGGREGATE_BEFORE_RETRAIN: whether the nightly job also rebuilds
# monthly_demand from stock_movements before retraining (i.e. calls the
# same thing /api/aggregate does) before calling run_forecast.
#
# DEFAULT IS OFF ON PURPOSE. aggregate_monthly_demand() TRUNCATES
# monthly_demand and rebuilds it entirely from stock_movements. If your
# monthly_demand rows came from somewhere else — e.g. the blended
# 3-year demo dataset in demo_data/, loaded directly into
# monthly_demand — turning this on would SILENTLY DELETE that data
# every night at AUTO_RETRAIN_HOUR.
#
# Turn this on only once your business is recording real stock
# movements day-to-day and you want monthly_demand to reflect them
# automatically. Until then, leave it off: the nightly job will just
# retrain on whatever is already in monthly_demand, which is safe
# regardless of how that data got there.
AUTO_AGGREGATE_BEFORE_RETRAIN = os.getenv("AUTO_AGGREGATE_BEFORE_RETRAIN", "0") == "1"
