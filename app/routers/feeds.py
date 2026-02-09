from datetime import datetime

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.models import Feedback, FeedbackAction, Feed, FeedItem, Item, SlotType, Source
from app.schemas import FeedCategoryGroup, FeedItemOut, FeedOut, Slot

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("/today", response_model=FeedOut)
def get_today_feed(
    slot: Slot = Query(...),
    db: Session = Depends(get_db),
):
    today = datetime.now().date()
    slot_type = SlotType.AM if slot == Slot.am else SlotType.PM

    feed = db.execute(select(Feed).where(and_(Feed.feed_date == today, Feed.slot == slot_type))).scalar_one_or_none()
    if not feed:
        raise HTTPException(status_code=404, detail="feed_not_generated")

    latest_feedback = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .group_by(Feedback.item_id)
        .subquery()
    )

    rows = db.execute(
        select(FeedItem, Item, Source, Feedback.action)
        .join(Item, FeedItem.item_id == Item.id)
        .join(Source, Item.source_id == Source.id)
        .outerjoin(latest_feedback, latest_feedback.c.item_id == Item.id)
        .outerjoin(Feedback, Feedback.id == latest_feedback.c.max_id)
        .where(FeedItem.feed_id == feed.id)
        .order_by(FeedItem.rank.asc())
    ).all()

    items = [
        FeedItemOut(
            item_id=item.id,
            title=item.title,
            source=source.name,
            category=source.category,
            url=item.url,
            short_reason=feed_item.short_reason,
            rank=feed_item.rank,
            saved=(action == FeedbackAction.SAVED),
        )
        for feed_item, item, source, action in rows
    ]

    grouped: dict[str, list[FeedItemOut]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    groups = [FeedCategoryGroup(category=cat, items=cat_items) for cat, cat_items in grouped.items()]
    return FeedOut(feed_date=str(feed.feed_date), slot=slot, generated_at=feed.generated_at, items=items, groups=groups)
