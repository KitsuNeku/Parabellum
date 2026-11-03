"""
Application configuration.

Values are read from environment variables with safe placeholder
fallbacks so this file is safe to commit. Real credentials are
supplied at runtime by the deployment platform's environment.
"""

import os
import secrets

# PostgreSQL connection parameters passed to psycopg2.connect().
# Values marked as placeholders must be overridden by environment
# variables in any environment that connects to a real database.
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "postgres"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "sslmode":  os.getenv("DB_SSLMODE", "prefer"),
}

# Flask session signing key. A per-process random fallback is generated
# when no SECRET_KEY is provided, which invalidates existing sessions on
# every restart. Production deployments supply a fixed value through
# the SECRET_KEY environment variable.
SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))

# Flask debug mode. Enables the interactive traceback console on error
# pages and must remain disabled in any environment reachable beyond
# localhost. Enabled by setting FLASK_DEBUG=1.
DEBUG = os.getenv("FLASK_DEBUG", "0") == "1"

# -----------------------------------------------------------------
# Automatic nightly retraining (see scheduler.py)
# -----------------------------------------------------------------
# Flag enabling the APScheduler job that calls run_forecast once per day.
AUTO_RETRAIN_ENABLED = os.getenv("AUTO_RETRAIN_ENABLED", "1") == "1"

# Hour of day (0-23, server local time) at which the retrain fires.
AUTO_RETRAIN_HOUR = int(os.getenv("AUTO_RETRAIN_HOUR", "2"))

# When enabled, aggregate_monthly_demand() runs before run_forecast()
# each night. aggregate_monthly_demand() truncates monthly_demand and
# rebuilds it from stock_movements; this flag must stay disabled when
# monthly_demand rows originate from an external seed rather than from
# recorded stock movements.
AUTO_AGGREGATE_BEFORE_RETRAIN = os.getenv("AUTO_AGGREGATE_BEFORE_RETRAIN", "0") == "1"
