from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.db import get_db
from app.models import Feed, ItemEvent, ItemEventType
from app.schemas import MetricsOut
from app.security import require_admin_token

router = APIRouter(prefix="/admin", tags=["admin"])
APP_TZ = ZoneInfo(settings.app_timezone)


def _window_or_400(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime, date, date]:
    try:
        to_date = date.fromisoformat(date_to) if date_to else datetime.now(APP_TZ).date()
        from_date = date.fromisoformat(date_from) if date_from else (to_date - timedelta(days=6))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_date_format") from None

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="invalid_date_range")

    start_local = datetime.combine(from_date, time.min, APP_TZ)
    end_local = datetime.combine(to_date + timedelta(days=1), time.min, APP_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC), from_date, to_date


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    _: None = Depends(require_admin_token),
    db: Session = Depends(get_db),
):
    start_dt, end_dt, from_date, to_date = _window_or_400(date_from, date_to)

    impressions = db.execute(
        select(func.count())
        .select_from(ItemEvent)
        .where(
            ItemEvent.event_type == ItemEventType.IMPRESSION.value,
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
    ).scalar_one()
    clicks = db.execute(
        select(func.count())
        .select_from(ItemEvent)
        .where(
            ItemEvent.event_type == ItemEventType.CLICK.value,
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
    ).scalar_one()
    generated_slots = db.execute(
        select(func.count())
        .select_from(Feed)
        .where(
            Feed.generated_at >= start_dt,
            Feed.generated_at < end_dt,
        )
    ).scalar_one()
    opened_slots = db.execute(
        select(func.count(func.distinct(ItemEvent.feed_id)))
        .where(
            ItemEvent.event_type == ItemEventType.IMPRESSION.value,
            ItemEvent.feed_id.is_not(None),
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
    ).scalar_one()

    ctr = (clicks / impressions) if impressions > 0 else 0.0
    slot_open_rate = (opened_slots / generated_slots) if generated_slots > 0 else 0.0
    return MetricsOut(
        date_from=str(from_date),
        date_to=str(to_date),
        impressions=impressions,
        clicks=clicks,
        generated_slots=generated_slots,
        opened_slots=opened_slots,
        ctr=ctr,
        slot_open_rate=slot_open_rate,
    )
