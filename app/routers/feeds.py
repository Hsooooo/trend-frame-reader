from datetime import datetime, timezone

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db import get_db
from app.models import Feedback, FeedbackAction, Item, ItemKeyword, Source, User
from app.schemas import FeedCategoryGroup, FeedItemOut, FeedOut, Slot
from app.security import get_optional_user
from app.services.events import CURATION_ACTIONS, PREFERENCE_ACTIONS
from app.services.feed_builder import current_period_info

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("/today", response_model=FeedOut)
def get_today_feed(
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    feed_date, slot_type, period_start = current_period_info(now)
    user_id = current_user.id if current_user else None

    # Curated item IDs to exclude (logged-in only)
    excluded_ids: list[int] = []
    if user_id is not None:
        latest_curation = (
            select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
            .where(
                Feedback.action.in_(list(CURATION_ACTIONS)),
                Feedback.user_id == user_id,
            )
            .group_by(Feedback.item_id)
            .subquery()
        )
        excluded_ids = list(
            db.execute(
                select(Feedback.item_id).join(latest_curation, Feedback.id == latest_curation.c.max_id)
            ).scalars().all()
        )

    # Dynamic item query from current period
    q = (
        select(Item, Source)
        .join(Source, Item.source_id == Source.id)
        .where(Item.fetched_at >= period_start)
    )
    if excluded_ids:
        q = q.where(Item.id.not_in(excluded_ids))

    if user_id is None:
        q = q.order_by(func.random())
    else:
        q = q.order_by(desc(Item.score), desc(Item.id))

    q = q.limit(settings.feed_max_items_total)
    item_source_rows = db.execute(q).all()

    if not item_source_rows:
        raise HTTPException(status_code=404, detail="feed_not_generated")

    item_ids = [item.id for item, _ in item_source_rows]

    # Keywords
    kw_map: dict[int, list[str]] = {}
    kw_rows = db.execute(
        select(ItemKeyword.item_id, ItemKeyword.keyword)
        .where(ItemKeyword.item_id.in_(item_ids))
        .order_by(ItemKeyword.item_id, ItemKeyword.relevance_score)
    ).all()
    for kw_item_id, keyword in kw_rows:
        kw_map.setdefault(kw_item_id, []).append(keyword)

    # Preference feedback (liked/disliked) for logged-in users
    pref_map: dict[int, str | None] = {}
    if user_id is not None:
        latest_pref = (
            select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
            .where(
                Feedback.action.in_(list(PREFERENCE_ACTIONS)),
                Feedback.user_id == user_id,
                Feedback.item_id.in_(item_ids),
            )
            .group_by(Feedback.item_id)
            .subquery()
        )
        pref_rows = db.execute(
            select(latest_pref.c.item_id, Feedback.action)
            .join(Feedback, Feedback.id == latest_pref.c.max_id)
        ).all()
        pref_map = {item_id: action for item_id, action in pref_rows}

    items = [
        FeedItemOut(
            item_id=item.id,
            title=item.title,
            translated_title_ko=item.translated_title_ko,
            source=source.name,
            category=source.category,
            url=item.url,
            short_reason=f"[{source.category}] Recent from {source.name}",
            rank=idx,
            saved=False,
            skipped=False,
            liked=(pref_map.get(item.id) == FeedbackAction.LIKED.value),
            disliked=(pref_map.get(item.id) == FeedbackAction.DISLIKED.value),
            curation_action=None,
            preference_action=pref_map.get(item.id),
            feedback_action=None,
            keywords=kw_map.get(item.id, []),
        )
        for idx, (item, source) in enumerate(item_source_rows, start=1)
    ]

    grouped: dict[str, list[FeedItemOut]] = {}
    for item in items:
        grouped.setdefault(item.category, []).append(item)

    slot = Slot.am if slot_type.value == "am" else Slot.pm
    groups = [FeedCategoryGroup(category=cat, items=cat_items) for cat, cat_items in grouped.items()]
    return FeedOut(feed_date=str(feed_date), slot=slot, generated_at=now, items=items, groups=groups)
