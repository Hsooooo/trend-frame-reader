from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.db import get_db
from app.models import Feedback, FeedbackAction, Feed, FeedItem, Item, SlotType, Source
from app.schemas import FeedCategoryGroup, FeedItemOut, FeedOut, Slot
from app.services.events import CURATION_ACTIONS, PREFERENCE_ACTIONS, create_feed_impression_events

router = APIRouter(prefix="/feeds", tags=["feeds"])
APP_TZ = ZoneInfo(settings.app_timezone)


@router.get("/today", response_model=FeedOut)
def get_today_feed(
    slot: Slot = Query(...),
    db: Session = Depends(get_db),
):
    today = datetime.now(APP_TZ).date()
    slot_type = SlotType.AM if slot == Slot.am else SlotType.PM

    feed = db.execute(select(Feed).where(and_(Feed.feed_date == today, Feed.slot == slot_type))).scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="feed_not_generated")

    latest_curation = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(Feedback.action.in_(list(CURATION_ACTIONS)))
        .group_by(Feedback.item_id)
        .subquery()
    )
    latest_preference = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(Feedback.action.in_(list(PREFERENCE_ACTIONS)))
        .group_by(Feedback.item_id)
        .subquery()
    )

    curation_feedback = aliased(Feedback)
    preference_feedback = aliased(Feedback)

    rows = db.execute(
        select(FeedItem, Item, Source, curation_feedback.action, preference_feedback.action)
        .join(Item, FeedItem.item_id == Item.id)
        .join(Source, Item.source_id == Source.id)
        .outerjoin(latest_curation, latest_curation.c.item_id == Item.id)
        .outerjoin(curation_feedback, curation_feedback.id == latest_curation.c.max_id)
        .outerjoin(latest_preference, latest_preference.c.item_id == Item.id)
        .outerjoin(preference_feedback, preference_feedback.id == latest_preference.c.max_id)
        .where(FeedItem.feed_id == feed.id)
        .order_by(FeedItem.rank.asc())
    ).all()

    items = [
        FeedItemOut(
            item_id=item.id,
            title=item.title,
            translated_title_ko=item.translated_title_ko,
            source=source.name,
            category=source.category,
            url=item.url,
            short_reason=feed_item.short_reason,
            rank=feed_item.rank,
            saved=(curation_action == FeedbackAction.SAVED.value),
            skipped=(curation_action == FeedbackAction.SKIPPED.value),
            liked=(preference_action == FeedbackAction.LIKED.value),
            disliked=(preference_action == FeedbackAction.DISLIKED.value),
            curation_action=curation_action,
            preference_action=preference_action,
            feedback_action=curation_action,
        )
        for feed_item, item, source, curation_action, preference_action in rows
    ]

    grouped: dict[str, list[FeedItemOut]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    impression_rows = [(item.id, feed_item.rank, source.id, source.category) for feed_item, item, source, _, _ in rows]
    try:
        create_feed_impression_events(db, feed.id, slot_type.value, impression_rows)
        db.commit()
    except Exception:
        db.rollback()

    groups = [FeedCategoryGroup(category=cat, items=cat_items) for cat, cat_items in grouped.items()]
    return FeedOut(feed_date=str(feed.feed_date), slot=slot, generated_at=feed.generated_at, items=items, groups=groups)
