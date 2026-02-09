from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import settings
from app.db import SessionLocal
from app.models import SlotType
from app.services.feed_builder import generate_feed_for_slot
from app.services.ingestion import run_ingestion

scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.app_timezone))


def _ingest_job():
    with SessionLocal() as db:
        run_ingestion(db)


def _feed_job(slot: SlotType):
    with SessionLocal() as db:
        generate_feed_for_slot(db, slot)


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(_ingest_job, "interval", minutes=30, id="ingestion_30m", replace_existing=True)
    scheduler.add_job(
        lambda: _feed_job(SlotType.AM),
        CronTrigger(hour=7, minute=30, timezone=ZoneInfo(settings.app_timezone)),
        id="feed_am",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: _feed_job(SlotType.PM),
        CronTrigger(hour=21, minute=30, timezone=ZoneInfo(settings.app_timezone)),
        id="feed_pm",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
