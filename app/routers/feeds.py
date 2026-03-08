from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session, aliased

from fastapi import APIRouter, Depends, HTTPException

from app.config import settings
from app.db import get_db
from app.models import Feedback, FeedbackAction, Feed, FeedItem, Item, ItemKeyword, SlotType, Source, SourceType, User
from app.mongo import get_market_articles_collection
from app.schemas import FeedCategoryGroup, FeedItemOut, FeedOut, Slot, StockFeedOut
from app.security import get_optional_user
from app.services.events import CURATION_ACTIONS, PREFERENCE_ACTIONS, create_feed_impression_events, create_impression_events
from app.services.feed_catalog import STOCK_FEED_CATEGORIES

router = APIRouter(prefix="/feeds", tags=["feeds"])
APP_TZ = ZoneInfo(settings.app_timezone)


def _feedback_scopes(user_id: int | None):
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
    return latest_curation, latest_preference, aliased(Feedback), aliased(Feedback)


def _keyword_map(db: Session, item_ids: list[int]) -> dict[int, list[str]]:
    kw_map: dict[int, list[str]] = {}
    if not item_ids:
        return kw_map

    kw_rows = db.execute(
        select(ItemKeyword.item_id, ItemKeyword.keyword)
        .where(ItemKeyword.item_id.in_(item_ids))
        .order_by(ItemKeyword.item_id, ItemKeyword.relevance_score)
    ).all()
    for kw_item_id, keyword in kw_rows:
        kw_map.setdefault(kw_item_id, []).append(keyword)
    return kw_map


def _published_at_str(item: Item) -> str | None:
    return item.published_at.isoformat() if item.published_at else None


def _market_ticker_map(item_ids: list[int]) -> dict[int, list[str]]:
    collection = get_market_articles_collection()
    if collection is None or not item_ids:
        return {}

    ticker_map: dict[int, list[str]] = {}
    rows = collection.find(
        {"item_id": {"$in": item_ids}},
        {"item_id": 1, "tickers.symbol": 1},
    )
    for row in rows:
        item_id = row.get("item_id")
        if item_id is None:
            continue
        seen_symbols: set[str] = set()
        symbols: list[str] = []
        for ticker_row in row.get("tickers", []):
            symbol = str(ticker_row.get("symbol", "")).upper().strip()
            if not symbol or symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            symbols.append(symbol)
        ticker_map[int(item_id)] = symbols
    return ticker_map


def _serialize_feed_item(
    *,
    item: Item,
    source: Source,
    rank: int,
    short_reason: str,
    kw_map: dict[int, list[str]],
    ticker_map: dict[int, list[str]],
    curation_action: str | None,
    preference_action: str | None,
) -> FeedItemOut:
    link_disabled = source.type == SourceType.ALPACA_NEWS
    return FeedItemOut(
        item_id=item.id,
        title=item.title,
        translated_title_ko=item.translated_title_ko,
        summary=item.summary,
        published_at=_published_at_str(item),
        source=source.name,
        category=source.category,
        url="" if link_disabled else item.url,
        link_disabled=link_disabled,
        short_reason=short_reason,
        rank=rank,
        saved=(curation_action == FeedbackAction.SAVED.value),
        skipped=(curation_action == FeedbackAction.SKIPPED.value),
        liked=(preference_action == FeedbackAction.LIKED.value),
        disliked=(preference_action == FeedbackAction.DISLIKED.value),
        curation_action=curation_action,
        preference_action=preference_action,
        feedback_action=curation_action,
        keywords=kw_map.get(item.id, []),
        tickers=ticker_map.get(item.id, []),
    )


def _stock_item_reason(item: Item, source: Source) -> str:
    published = item.published_at or item.fetched_at
    published_label = published.astimezone(APP_TZ).strftime("%Y-%m-%d %H:%M")
    return f"Latest from {source.name} · {published_label}"


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
    latest_curation, latest_preference, curation_feedback, preference_feedback = _feedback_scopes(user_id)

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
    kw_map = _keyword_map(db, item_ids)
    ticker_map = _market_ticker_map(item_ids)
    items = [
        _serialize_feed_item(
            item=item,
            source=source,
            rank=feed_item.rank,
            short_reason=feed_item.short_reason,
            kw_map=kw_map,
            ticker_map=ticker_map,
            curation_action=curation_action,
            preference_action=preference_action,
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


@router.get("/stocks", response_model=StockFeedOut)
def get_stock_feed(
    current_user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    user_id = current_user.id if current_user else None
    latest_curation, latest_preference, curation_feedback, preference_feedback = _feedback_scopes(user_id)
    sort_ts = func.coalesce(Item.published_at, Item.fetched_at)

    rows = db.execute(
        select(Item, Source, curation_feedback.action, preference_feedback.action)
        .join(Source, Item.source_id == Source.id)
        .outerjoin(latest_curation, latest_curation.c.item_id == Item.id)
        .outerjoin(curation_feedback, curation_feedback.id == latest_curation.c.max_id)
        .outerjoin(latest_preference, latest_preference.c.item_id == Item.id)
        .outerjoin(preference_feedback, preference_feedback.id == latest_preference.c.max_id)
        .where(Source.category.in_(tuple(STOCK_FEED_CATEGORIES)))
        .order_by(desc(sort_ts), desc(Item.id))
        .limit(settings.stock_feed_limit)
    ).all()

    item_ids = [item.id for item, *_ in rows]
    kw_map = _keyword_map(db, item_ids)
    ticker_map = _market_ticker_map(item_ids)
    items = [
        _serialize_feed_item(
            item=item,
            source=source,
            rank=rank,
            short_reason=_stock_item_reason(item, source),
            kw_map=kw_map,
            ticker_map=ticker_map,
            curation_action=curation_action,
            preference_action=preference_action,
        )
        for rank, (item, source, curation_action, preference_action) in enumerate(rows, start=1)
    ]

    try:
        create_impression_events(
            db,
            [(item.id, rank, source.id, source.category) for rank, (item, source, _, _) in enumerate(rows, start=1)],
            slot="stocks",
        )
        db.commit()
    except Exception:
        db.rollback()

    latest_generated_at = None
    if rows:
        latest_generated_at = max((item.fetched_at for item, *_ in rows), default=None)

    return StockFeedOut(
        generated_at=latest_generated_at,
        items=items,
        groups=[FeedCategoryGroup(category="stock-feed", items=items)] if items else [],
    )
