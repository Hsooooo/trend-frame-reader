from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Feed, FeedItem, Feedback, FeedbackAction, Item, ItemEvent, ItemEventType, Source

CURATION_ACTIONS = {FeedbackAction.SAVED.value, FeedbackAction.SKIPPED.value}
PREFERENCE_ACTIONS = {FeedbackAction.LIKED.value, FeedbackAction.DISLIKED.value}
ALL_FEEDBACK_ACTIONS = CURATION_ACTIONS | PREFERENCE_ACTIONS


def _latest_feed_context_for_item(db: Session, item_id: int) -> dict:
    row = db.execute(
        select(FeedItem.feed_id, Feed.slot, FeedItem.rank)
        .join(Feed, Feed.id == FeedItem.feed_id)
        .where(FeedItem.item_id == item_id)
        .order_by(desc(Feed.generated_at), desc(FeedItem.id))
        .limit(1)
    ).first()
    if not row:
        return {"feed_id": None, "slot": None, "rank": None}

    feed_id, slot, rank = row
    slot_value = slot.value if hasattr(slot, "value") else str(slot)
    return {"feed_id": feed_id, "slot": slot_value, "rank": rank}


def _latest_impression_context_for_item(db: Session, item_id: int) -> dict | None:
    row = db.execute(
        select(ItemEvent.feed_id, ItemEvent.slot, ItemEvent.rank)
        .where(
            ItemEvent.item_id == item_id,
            ItemEvent.event_type == ItemEventType.IMPRESSION.value,
        )
        .order_by(desc(ItemEvent.created_at), desc(ItemEvent.id))
        .limit(1)
    ).first()
    if not row:
        return None

    feed_id, slot, rank = row
    return {"feed_id": feed_id, "slot": slot, "rank": rank}


def get_item_event_context(db: Session, item_id: int) -> dict | None:
    item_row = db.execute(
        select(Item.id, Item.source_id, Source.category)
        .join(Source, Source.id == Item.source_id)
        .where(Item.id == item_id)
    ).first()
    if not item_row:
        return None

    _, source_id, category = item_row
    feed_ctx = _latest_impression_context_for_item(db, item_id) or _latest_feed_context_for_item(db, item_id)
    return {
        "source_id": source_id,
        "category": category,
        "feed_id": feed_ctx["feed_id"],
        "slot": feed_ctx["slot"],
        "rank": feed_ctx["rank"],
    }


def create_feedback_with_context(db: Session, item_id: int, action: str, user_id: int | None = None) -> Feedback:
    ctx = get_item_event_context(db, item_id)
    if not ctx:
        raise ValueError("item_not_found")

    row = Feedback(
        item_id=item_id,
        action=action,
        slot=ctx["slot"],
        rank=ctx["rank"],
        source_id=ctx["source_id"],
        category=ctx["category"],
        feed_id=ctx["feed_id"],
        user_id=user_id,
    )
    db.add(row)
    return row


def create_item_event(db: Session, item_id: int, event_type: str, user_id: int | None = None) -> ItemEvent:
    ctx = get_item_event_context(db, item_id)
    if not ctx:
        raise ValueError("item_not_found")

    row = ItemEvent(
        item_id=item_id,
        event_type=event_type,
        slot=ctx["slot"],
        rank=ctx["rank"],
        source_id=ctx["source_id"],
        category=ctx["category"],
        feed_id=ctx["feed_id"],
        user_id=user_id,
    )
    db.add(row)
    return row


def create_feed_impression_events(
    db: Session,
    feed_id: int,
    slot: str,
    rows: list[tuple[int, int, int, str]],
) -> int:
    return create_impression_events(db, rows, slot=slot, feed_id=feed_id)


def create_impression_events(
    db: Session,
    rows: list[tuple[int, int, int, str]],
    *,
    slot: str | None = None,
    feed_id: int | None = None,
) -> int:
    for item_id, rank, source_id, category in rows:
        db.add(
            ItemEvent(
                item_id=item_id,
                event_type=ItemEventType.IMPRESSION.value,
                feed_id=feed_id,
                slot=slot,
                rank=rank,
                source_id=source_id,
                category=category,
            )
        )
    return len(rows)
