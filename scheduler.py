"""
Parabellum ISOS - Automatic Nightly Retraining
=================================================================
Wraps APScheduler so the MLR retrains itself once a day, with no one
needing to click "Generate Forecast". Same model, same math, same
in-sample evaluation as a manual run — this only changes WHEN
run_forecast() gets called, never HOW it works.

WHAT THIS DOES
    Once a day, at config.AUTO_RETRAIN_HOUR (server local time):
      1. (only if config.AUTO_AGGREGATE_BEFORE_RETRAIN is True)
         rebuild monthly_demand from stock_movements, exactly like
         POST /api/aggregate does.
      2. Call run_forecast() exactly like POST /api/forecast does.
      3. Log the outcome (success or failure) to audit_logs so it's
         visible in the same Prediction History / audit trail as any
         manually triggered run.

WHAT THIS DELIBERATELY DOES NOT DO
    - It does not change the model itself. There is no online/
      incremental learning here - every run is a full retrain from
      whatever is currently in monthly_demand, same as a manual click.
    - It does not touch monthly_demand unless AUTO_AGGREGATE_BEFORE_RETRAIN
      is explicitly turned on (see config.py for why that matters).
    - It does not retry on failure within the same day. If a nightly
      run fails (e.g. not enough data yet), it logs the failure and
      waits for tomorrow's scheduled run - it does not spam retries.

DEPLOYMENT NOTE - read this before relying on it in production:
    This uses APScheduler's BackgroundScheduler, which runs INSIDE the
    Flask process. That's the right choice for a single-process
    deployment (e.g. `python app.py`, or a single gunicorn worker).

    If you ever deploy with multiple worker processes (e.g.
    `gunicorn -w 4 app:app`), EVERY worker will start its own copy of
    this scheduler, so the nightly retrain would fire 4 times instead
    of once. Nothing breaks (forecast_results and model_metrics just
    get harmlessly overwritten by each duplicate run, and audit_logs
    gets a few duplicate entries), but it's wasteful and confusing to
    read. For a multi-worker deployment, disable AUTO_RETRAIN_ENABLED
    in the app itself and instead run this job from ONE external cron
    process (e.g. a separate `python -c "from scheduler import run_once;
    run_once()"` invoked by system cron once a day).
"""

import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from mlr_model import aggregate_monthly_demand, run_forecast, log_audit

logger = logging.getLogger("parabellum.scheduler")

_scheduler = None          # module-level singleton, set by start()
_last_run_info = {         # surfaced by /api/scheduler/status in app.py
    "last_run_at":  None,
    "last_status":  None,   # "success" | "failed" | None (never run yet)
    "last_message": None,
}


def run_once(db_config, auto_aggregate=False):
    """
    Execute one retrain cycle. Safe to call directly (e.g. from a cron
    job, a test, or a manual "retrain now" button) as well as from the
    scheduled job below - this function IS the job, just callable on
    its own.
    """
    started_at = datetime.now()
    try:
        agg_note = ""
        if auto_aggregate:
            n_rows = aggregate_monthly_demand(db_config)
            agg_note = f"Rebuilt monthly_demand ({n_rows} rows). "

        result = run_forecast(db_config, username="scheduler")

        n_forecasts = len(result["forecasts"])
        message = (
            f"{agg_note}Retrained and forecasted {result['forecast_month']} "
            f"for {n_forecasts} materials. Pooled R²={result['metrics']['r2']}, "
            f"MAE={result['metrics']['mae']}."
        )
        log_audit(db_config, "SCHEDULED_RETRAIN", message, username="scheduler")

        _last_run_info.update(
            last_run_at=started_at.isoformat(timespec="seconds"),
            last_status="success",
            last_message=message,
        )
        logger.info("Scheduled retrain succeeded: %s", message)
        return True, message

    except Exception as e:
        # A failed nightly run must never crash the Flask process or
        # take down the scheduler - log it and wait for tomorrow.
        message = f"Scheduled retrain failed: {e}"
        try:
            log_audit(db_config, "SCHEDULED_RETRAIN_FAILED", message, username="scheduler")
        except Exception:
            pass  # even audit logging can fail if the DB is unreachable

        _last_run_info.update(
            last_run_at=started_at.isoformat(timespec="seconds"),
            last_status="failed",
            last_message=message,
        )
        logger.exception("Scheduled retrain failed")
        return False, message


def get_status():
    """
    Returns what /api/scheduler/status reports: whether the scheduler
    is running, when it will next fire, and the outcome of the last run.
    """
    next_run = None
    if _scheduler is not None:
        job = _scheduler.get_job("nightly_retrain")
        if job is not None and job.next_run_time is not None:
            next_run = job.next_run_time.isoformat(timespec="seconds")
    return {
        "enabled":      _scheduler is not None,
        "next_run_at":  next_run,
        **_last_run_info,
    }


def start(db_config, hour=2, auto_aggregate=False):
    """
    Start the background scheduler. Call this ONCE at app startup, only
    from the single process that should own the nightly job (see the
    multi-worker caveat in the module docstring, and the Flask-reloader
    guard app.py applies before calling this).
    """
    global _scheduler
    if _scheduler is not None:
        return _scheduler  # already started - don't double-register

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        func=lambda: run_once(db_config, auto_aggregate=auto_aggregate),
        trigger=CronTrigger(hour=hour, minute=0),
        id="nightly_retrain",
        name="Nightly MLR retrain",
        replace_existing=True,
        misfire_grace_time=3600,  # if the server was down at 2am, still
                                  # run within an hour of coming back up
    )
    _scheduler.start()
    logger.info("Nightly retrain scheduler started - fires daily at %02d:00.", hour)
    return _scheduler


def shutdown():
    """Call on app teardown so the background thread exits cleanly."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
