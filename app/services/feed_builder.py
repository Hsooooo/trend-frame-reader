from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
import random
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Feedback, Feed, FeedItem, Item, Job, SlotType
from app.services.events import CURATION_ACTIONS
from app.services.utils import utcnow

APP_TZ = ZoneInfo(settings.app_timezone)


def _reason(item: Item) -> str:
    return f"[{item.source.category}] Recent from {item.source.name}"


def _pick_next_item(
    items: list[Item],
    cursor: int,
    used_domains: set[str],
):
    idx = cursor
    fallback_idx = None
    fallback_item = None
    while idx < len(items):
        item = items[idx]
        domain = urlparse(item.canonical_url).netloc
        if domain not in used_domains:
            return idx + 1, item
        if fallback_item is None:
            fallback_idx = idx
            fallback_item = item
        idx += 1
    if fallback_item is not None and fallback_idx is not None:
        # Degrade path: allow duplicate domains when diversity blocks minimum fill.
        return fallback_idx + 1, fallback_item
    return idx, None


def generate_feed_for_slot(db: Session, slot: SlotType):
    started = utcnow()
    job = Job(job_type=f"feed_generation_{slot.value}", started_at=started, status="running")
    db.add(job)
    db.flush()

    try:
        now = utcnow()
        today = now.astimezone(APP_TZ).date()

        existing = db.execute(select(Feed).where(and_(Feed.feed_date == today, Feed.slot == slot))).scalar_one_or_none()
        if existing:
            db.execute(delete(FeedItem).where(FeedItem.feed_id == existing.id))
            feed = existing
            feed.generated_at = now
        else:
            feed = Feed(feed_date=today, slot=slot, generated_at=now)
            db.add(feed)
            db.flush()

        latest_feedback = (
            select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
            .where(Feedback.action.in_(list(CURATION_ACTIONS)))
            .group_by(Feedback.item_id)
            .subquery()
        )
        excluded_items = (
            select(Feedback.item_id)
            .join(latest_feedback, Feedback.id == latest_feedback.c.max_id)
        )

        cutoff = now - timedelta(hours=settings.ingestion_lookback_hours)
        items = db.execute(
            select(Item)
            .where(Item.fetched_at >= cutoff, Item.id.not_in(excluded_items))
            .order_by(desc(Item.score), desc(Item.id))
            .limit(max(300, settings.feed_max_items_total * 20))
        ).scalars().all()

        picked = []
        used_domains = set()

        by_category: dict[str, list[Item]] = defaultdict(list)
        for item in items:
            by_category[item.source.category].append(item)

        rng = random.Random()
        for cat_items in by_category.values():
            rng.shuffle(cat_items)

        categories = sorted(by_category.keys(), key=lambda c: by_category[c][0].score if by_category[c] else 0, reverse=True)
        target_per_category = max(1, settings.feed_target_items_per_category)
        per_category_cap = max(target_per_category, settings.feed_max_items_per_category)
        total_cap = max(per_category_cap, settings.feed_max_items_total)
        cat_counts = {cat: 0 for cat in categories}
        cat_cursor = {cat: 0 for cat in categories}

        # Pass 1: spread across categories first, aiming for target_per_category.
        for _ in range(target_per_category):
            for category in categories:
                if len(picked) >= total_cap:
                    break
                cat_cursor[category], item = _pick_next_item(
                    by_category[category],
                    cat_cursor[category],
                    used_domains,
                )
                if not item:
                    continue
                used_domains.add(urlparse(item.canonical_url).netloc)
                picked.append(item)
                cat_counts[category] += 1

        # Pass 2: fill remaining capacity up to per-category hard cap.
        for category in categories:
            while cat_counts[category] < per_category_cap and len(picked) < total_cap:
                cat_cursor[category], item = _pick_next_item(
                    by_category[category],
                    cat_cursor[category],
                    used_domains,
                )
                if not item:
                    break
                used_domains.add(urlparse(item.canonical_url).netloc)
                picked.append(item)
                cat_counts[category] += 1

        if len(picked) < settings.feed_min_items:
            fallback = db.execute(select(Item).order_by(desc(Item.score), desc(Item.id)).limit(settings.feed_min_items)).scalars().all()
            seen = {x.id for x in picked}
            for item in fallback:
                if item.id in seen:
                    continue
                picked.append(item)
                if len(picked) >= settings.feed_min_items:
                    break

        for idx, item in enumerate(picked, start=1):
            db.add(
                FeedItem(
                    feed_id=feed.id,
                    item_id=item.id,
                    rank=idx,
                    short_reason=_reason(item),
                )
            )

        job.status = "success"
        job.ended_at = utcnow()
        db.commit()
        return feed.id
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)
        job.ended_at = utcnow()
        db.add(job)
        db.commit()
        raise
