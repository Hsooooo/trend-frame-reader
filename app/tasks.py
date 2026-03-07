from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.models import SlotType
from app.services.feed_builder import generate_feed_for_slot
from app.services.ingestion import run_ingestion
from app.services.market_backfill_jobs import (
    process_market_backfill_job,
    resume_pending_market_backfill_jobs,
)

scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.app_timezone))
APP_TZ = ZoneInfo(settings.app_timezone)


def _ingest_job():
    with SessionLocal() as db:
        run_ingestion(db)


def _feed_job(slot: SlotType):
    with SessionLocal() as db:
        generate_feed_for_slot(db, slot)


def _hourly_refresh_job():
    # Refresh both slots hourly from the latest ingested item pool.
    with SessionLocal() as db:
        generate_feed_for_slot(db, SlotType.AM)
    with SessionLocal() as db:
        generate_feed_for_slot(db, SlotType.PM)


def _market_backfill_job(job_id: int):
    result = process_market_backfill_job(job_id)
    paused_until_raw = result.get("paused_until")
    if result.get("status") == "paused" and paused_until_raw:
        try:
            paused_until = datetime.fromisoformat(paused_until_raw)
        except ValueError:
            paused_until = datetime.now(UTC)
        schedule_market_backfill_job(job_id, paused_until)


def schedule_market_backfill_job(job_id: int, run_at: datetime | None = None):
    run_date = run_at or datetime.now(UTC)
    scheduler.add_job(
        _market_backfill_job,
        "date",
        run_date=run_date,
        id=f"market_backfill_{job_id}",
        replace_existing=True,
        args=[job_id],
    )


def _resume_market_backfill_jobs():
    jobs = resume_pending_market_backfill_jobs()
    now = datetime.now(UTC)
    for job in jobs:
        paused_until = job.get("paused_until")
        run_at = None
        if job.get("status") == "paused" and paused_until:
            try:
                parsed = datetime.fromisoformat(paused_until)
                run_at = parsed if parsed > now else now
            except ValueError:
                run_at = now
        schedule_market_backfill_job(job["job_id"], run_at)


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(_ingest_job, "interval", minutes=30, id="ingestion_30m", replace_existing=True)
    scheduler.add_job(
        _hourly_refresh_job,
        CronTrigger(minute=5, timezone=APP_TZ),
        id="feed_hourly_refresh",
        replace_existing=True,
    )
    scheduler.start()
    _resume_market_backfill_jobs()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
