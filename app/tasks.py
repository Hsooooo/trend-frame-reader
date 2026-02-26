from datetime import timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.services.feed_builder import current_period_info, generate_feed_for_slot
from app.services.ingestion import run_ingestion
from app.services.utils import utcnow

scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.app_timezone))
APP_TZ = ZoneInfo(settings.app_timezone)


def _ingest_job():
    with SessionLocal() as db:
        run_ingestion(db)


def _hourly_refresh_job():
    feed_date, slot, period_start = current_period_info(utcnow())
    with SessionLocal() as db:
        generate_feed_for_slot(db, slot, feed_date=feed_date, period_start=period_start)


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
    scheduler.add_job(
        _hourly_refresh_job,
        CronTrigger(hour=6, minute=0, timezone=APP_TZ),
        id="feed_day_start",
        replace_existing=True,
    )
    scheduler.add_job(
        _hourly_refresh_job,
        CronTrigger(hour=18, minute=0, timezone=APP_TZ),
        id="feed_night_start",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
