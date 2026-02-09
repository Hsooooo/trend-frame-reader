from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import and_, delete, desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Feed, FeedItem, Item, Job, SlotType
from app.services.utils import utcnow


def _reason(item: Item) -> str:
    return f"[{item.source.category}] Recent from {item.source.name}"


def generate_feed_for_slot(db: Session, slot: SlotType):
    started = utcnow()
    job = Job(job_type=f"feed_generation_{slot.value}", started_at=started, status="running")
    db.add(job)
    db.flush()

    try:
        now = utcnow()
        today = now.date()

        existing = db.execute(select(Feed).where(and_(Feed.feed_date == today, Feed.slot == slot))).scalar_one_or_none()
        if existing:
            db.execute(delete(FeedItem).where(FeedItem.feed_id == existing.id))
            feed = existing
            feed.generated_at = now
        else:
            feed = Feed(feed_date=today, slot=slot, generated_at=now)
            db.add(feed)
            db.flush()

        cutoff = now - timedelta(hours=settings.ingestion_lookback_hours)
        items = db.execute(
            select(Item)
            .where(Item.fetched_at >= cutoff)
            .order_by(desc(Item.score), desc(Item.id))
            .limit(300)
        ).scalars().all()

        picked = []
        used_domains = set()

        by_category: dict[str, list[Item]] = defaultdict(list)
        for item in items:
            by_category[item.source.category].append(item)

        # Round-robin across categories first to avoid one-category feed domination.
        categories = sorted(by_category.keys(), key=lambda c: by_category[c][0].score if by_category[c] else 0, reverse=True)
        index_map = {c: 0 for c in categories}

        while len(picked) < settings.feed_max_items:
            progressed = False
            for category in categories:
                idx = index_map[category]
                bucket = by_category[category]
                while idx < len(bucket):
                    item = bucket[idx]
                    idx += 1
                    domain = urlparse(item.canonical_url).netloc
                    if domain in used_domains:
                        continue
                    used_domains.add(domain)
                    picked.append(item)
                    progressed = True
                    break
                index_map[category] = idx
                if len(picked) >= settings.feed_max_items:
                    break
            if not progressed:
                break

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
