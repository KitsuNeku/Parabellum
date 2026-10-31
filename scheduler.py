import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db import log_audit
from mlr_model import aggregate_monthly_demand, run_forecast
import digest
import weather_api

TIMEZONE = "Asia/Manila"

logger = logging.getLogger("parabellum.scheduler")

_scheduler = None
_last_run_info = {
    "last_run_at":  None,
    "last_status":  None,
    "last_message": None,
}


def run_once(db_config, auto_aggregate=False):
    started_at = datetime.now()
    try:
        agg_note = ""
        if auto_aggregate:
            n_rows = aggregate_monthly_demand(db_config)
            agg_note = f"Rebuilt monthly_demand ({n_rows} rows). "

        try:
            weather_api.sync_for_history(db_config, username="scheduler")
        except Exception:
            logger.warning("Weather sync skipped (weather service unreachable).")
        result = run_forecast(db_config, username="scheduler")

        n_forecasts = len(result["forecasts"])
        ev = (result.get("evaluation") or {}).get("models", [{}])[0]
        message = (
            f"{agg_note}Retrained and forecasted {result['forecast_month']} "
            f"for {n_forecasts} materials."
            + (f" Hold-out MAE={ev.get('mae')}, MAPE={ev.get('mape')}%." if ev else "")
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
        message = f"Scheduled retrain failed: {e}"
        try:
            log_audit(db_config, "SCHEDULED_RETRAIN_FAILED", message, username="scheduler")
        except Exception:
            pass

        _last_run_info.update(
            last_run_at=started_at.isoformat(timespec="seconds"),
            last_status="failed",
            last_message=message,
        )
        logger.exception("Scheduled retrain failed")
        return False, message


def get_status():
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
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    _scheduler = BackgroundScheduler(daemon=True, timezone=TIMEZONE)
    _scheduler.add_job(
        func=lambda: run_once(db_config, auto_aggregate=auto_aggregate),
        trigger=CronTrigger(hour=hour, minute=0, timezone=TIMEZONE),
        id="nightly_retrain",
        name="Nightly MLR retrain",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        func=lambda: digest.send_weekly(db_config),
        trigger=CronTrigger(day_of_week="mon", hour=8, minute=0, timezone=TIMEZONE),
        id="weekly_digest",
        name="Weekly email digest",
        replace_existing=True,
        misfire_grace_time=6 * 3600,
    )
    _scheduler.start()
    logger.info("Nightly retrain scheduler started - fires daily at %02d:00.", hour)
    return _scheduler


def shutdown():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
