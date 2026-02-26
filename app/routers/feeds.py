from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, aliased

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db import get_db
from app.models import Feedback, FeedbackAction, Feed, FeedItem, Item, ItemKeyword, SlotType, Source, User
from app.schemas import FeedCategoryGroup, FeedItemOut, FeedOut, Slot
from app.security import get_optional_user
from app.services.events import CURATION_ACTIONS, PREFERENCE_ACTIONS, create_feed_impression_events

router = APIRouter(prefix="/feeds", tags=["feeds"])
APP_TZ = ZoneInfo(settings.app_timezone)


@router.get("/today", response_model=FeedOut)
def get_today_feed(
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    now_local = datetime.now(APP_TZ)
    today = now_local.date()
    primary_slot = SlotType.AM if 6 <= now_local.hour < 18 else SlotType.PM
    fallback_slot = SlotType.PM if primary_slot == SlotType.AM else SlotType.AM

    feed = None
    slot_type = primary_slot
    for candidate_slot in (primary_slot, fallback_slot):
        feed = db.execute(
            select(Feed).where(and_(Feed.feed_date == today, Feed.slot == candidate_slot))
        ).scalar_one_or_none()
        if feed is not None:
            slot_type = candidate_slot
            break

    if not feed:
        raise HTTPException(status_code=404, detail="feed_not_generated")

    user_id = current_user.id if current_user else None

    curation_filter = [Feedback.action.in_(list(CURATION_ACTIONS))]
    preference_filter = [Feedback.action.in_(list(PREFERENCE_ACTIONS))]
    if user_id is not None:
        curation_filter.append(Feedback.user_id == user_id)
        preference_filter.append(Feedback.user_id == user_id)

    latest_curation = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(*curation_filter)
        .group_by(Feedback.item_id)
        .subquery()
    )
    latest_preference = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(*preference_filter)
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

    item_ids = [item.id for _, item, *_ in rows]
    kw_map: dict[int, list[str]] = {}
    if item_ids:
        kw_rows = db.execute(
            select(ItemKeyword.item_id, ItemKeyword.keyword)
            .where(ItemKeyword.item_id.in_(item_ids))
            .order_by(ItemKeyword.item_id, ItemKeyword.relevance_score)
        ).all()
        for kw_item_id, keyword in kw_rows:
            kw_map.setdefault(kw_item_id, []).append(keyword)

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
            keywords=kw_map.get(item.id, []),
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

    slot = Slot.am if slot_type == SlotType.AM else Slot.pm
    groups = [FeedCategoryGroup(category=cat, items=cat_items) for cat, cat_items in grouped.items()]
    return FeedOut(feed_date=str(feed.feed_date), slot=slot, generated_at=feed.generated_at, items=items, groups=groups)
