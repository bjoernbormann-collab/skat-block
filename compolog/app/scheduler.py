"""Background jobs (Querschnittsanforderung).

APScheduler rather than Celery: Celery needs a broker process, and a single Mac
mini with one user does not benefit from that. The interface here is narrow
enough that swapping it out later is a contained change.

Jobs are registered in one place so that "what runs when" is answerable by
reading one file.

STUB NOTICE: only the housekeeping jobs are wired up. The eBay sync, token
refresh and retry-queue jobs are registered as explicit placeholders that log a
warning if called -- they arrive with Modul 2 and must not silently do nothing.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import session_scope
from app.logging_config import get_logger
from app.security import purge_expired_sessions
from app.services.backup import run_backup

logger = get_logger("scheduler")

scheduler = BackgroundScheduler(timezone="Europe/Berlin")


def job_backup() -> None:
    try:
        run_backup()
    except Exception:
        # A failing backup must be loud but must never take the app down.
        logger.exception("backup_failed")


def job_purge_sessions() -> None:
    with session_scope() as db:
        removed = purge_expired_sessions(db)
    if removed:
        logger.info("sessions_purged", extra={"removed": removed})


def register_jobs() -> None:
    if settings.backup_enabled:
        scheduler.add_job(
            job_backup,
            CronTrigger(hour=settings.backup_cron_hour, minute=0),
            id="daily_backup",
            replace_existing=True,
        )
    scheduler.add_job(
        job_purge_sessions,
        CronTrigger(hour=4, minute=30),
        id="purge_sessions",
        replace_existing=True,
    )
    # Modul 2 adds here:
    #   ebay_sync          every settings.ebay_sync_interval_minutes
    #   ebay_token_refresh hourly (access token lives 2 h)
    #   sync_retry_queue   every 5 minutes


def start() -> None:
    register_jobs()
    scheduler.start()
    logger.info("scheduler_started",
                extra={"jobs": [job.id for job in scheduler.get_jobs()]})


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
