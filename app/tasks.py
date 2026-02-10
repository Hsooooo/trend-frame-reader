from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.models import SlotType
from app.services.feed_builder import generate_feed_for_slot
from app.services.ingestion import run_ingestion

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


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
