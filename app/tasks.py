from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.db import SessionLocal
from app.services.ingestion import run_ingestion

scheduler = BackgroundScheduler(timezone=ZoneInfo(settings.app_timezone))


def _ingest_job():
    with SessionLocal() as db:
        run_ingestion(db)


def start_scheduler():
    if scheduler.running:
        return

    scheduler.add_job(_ingest_job, "interval", minutes=30, id="ingestion_30m", replace_existing=True)
    scheduler.start()


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
