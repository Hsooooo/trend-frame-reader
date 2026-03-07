from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Job, Item, ItemKeyword, Source
from app.mongo import get_market_articles_collection
from app.services.market_entities import MarketEntityRateLimitedError
from app.services.market_graph import get_existing_market_article_ids, sync_market_article

logger = logging.getLogger(__name__)

MARKET_GRAPH_BACKFILL_JOB_TYPE = "market_graph_backfill"
ACTIVE_MARKET_GRAPH_BACKFILL_STATUSES = {"queued", "running", "paused"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _serialize_job(job: Job) -> dict:
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "processed": job.processed_items,
        "synced": job.synced_items,
        "failed": job.failed_items,
        "total": job.total_items,
        "last_item_id": job.last_item_id,
        "limit": job.limit_value,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "ended_at": job.ended_at.isoformat() if job.ended_at else None,
        "paused_until": job.paused_until.isoformat() if job.paused_until else None,
        "error_message": job.error_message,
    }


def get_market_backfill_job(db: Session, job_id: int) -> Job | None:
    job = db.get(Job, job_id)
    if job is None or job.job_type != MARKET_GRAPH_BACKFILL_JOB_TYPE:
        return None
    return job


def get_latest_market_backfill_job(db: Session) -> Job | None:
    return db.execute(
        select(Job)
        .where(Job.job_type == MARKET_GRAPH_BACKFILL_JOB_TYPE)
        .order_by(Job.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_active_market_backfill_job(db: Session) -> Job | None:
    return db.execute(
        select(Job)
        .where(
            Job.job_type == MARKET_GRAPH_BACKFILL_JOB_TYPE,
            Job.status.in_(ACTIVE_MARKET_GRAPH_BACKFILL_STATUSES),
        )
        .order_by(Job.id.desc())
        .limit(1)
    ).scalar_one_or_none()


def serialize_market_backfill_job(job: Job) -> dict:
    return _serialize_job(job)


def create_or_reuse_market_backfill_job(
    db: Session,
    *,
    requested_by_user_id: int | None,
    limit: int | None = None,
) -> tuple[Job, bool]:
    active_job = get_active_market_backfill_job(db)
    if active_job is not None:
        return active_job, False

    total_items = _count_target_items(db, after_item_id=0, limit=limit)
    now = _utcnow()
    job = Job(
        job_type=MARKET_GRAPH_BACKFILL_JOB_TYPE,
        requested_by_user_id=requested_by_user_id,
        started_at=now,
        ended_at=now if total_items == 0 else None,
        status="completed" if total_items == 0 else "queued",
        error_message=None,
        total_items=total_items,
        processed_items=0,
        synced_items=0,
        failed_items=0,
        last_item_id=None,
        limit_value=limit,
        paused_until=None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job, True


def _count_target_items(db: Session, *, after_item_id: int, limit: int | None) -> int:
    total = db.execute(
        select(func.count())
        .select_from(Item)
        .where(Item.id > after_item_id)
    ).scalar_one()
    if limit is not None and limit > 0:
        return min(int(total), limit)
    return int(total)


def _fetch_batch_items(
    db: Session,
    *,
    after_item_id: int,
    batch_size: int,
) -> list[Item]:
    return db.execute(
        select(Item)
        .where(Item.id > after_item_id)
        .order_by(Item.id)
        .limit(batch_size)
    ).scalars().all()


def _load_batch_context(db: Session, items: list[Item]) -> tuple[dict[int, Source], dict[int, list[str]]]:
    if not items:
        return {}, {}

    source_ids = {item.source_id for item in items}
    sources = db.execute(select(Source).where(Source.id.in_(source_ids))).scalars().all()
    sources_map = {source.id: source for source in sources}

    item_ids = [item.id for item in items]
    kw_rows = db.execute(
        select(ItemKeyword.item_id, ItemKeyword.keyword)
        .where(ItemKeyword.item_id.in_(item_ids))
    ).all()
    keywords_by_item: dict[int, list[str]] = {}
    for item_id, keyword in kw_rows:
        keywords_by_item.setdefault(item_id, []).append(keyword)

    return sources_map, keywords_by_item


def _mark_job_completed(job: Job) -> None:
    job.status = "completed" if job.failed_items == 0 else "completed_with_errors"
    job.ended_at = _utcnow()
    job.paused_until = None


def _mark_job_failed(job: Job, message: str) -> None:
    job.status = "failed"
    job.error_message = message
    job.ended_at = _utcnow()
    job.paused_until = None


def process_market_backfill_job(job_id: int) -> dict:
    while True:
        with SessionLocal() as db:
            job = get_market_backfill_job(db, job_id)
            if job is None:
                return {"status": "missing", "job_id": job_id}

            now = _utcnow()
            if job.status not in ACTIVE_MARKET_GRAPH_BACKFILL_STATUSES:
                return _serialize_job(job)

            if job.paused_until is not None and job.paused_until > now:
                return _serialize_job(job)

            if job.status != "running":
                job.status = "running"
                job.error_message = None
                job.paused_until = None
                db.commit()
                db.refresh(job)

            if get_market_articles_collection() is None:
                _mark_job_failed(job, "market_articles_collection_unavailable")
                db.commit()
                return _serialize_job(job)

            remaining = max(job.total_items - job.processed_items, 0)
            if remaining == 0:
                _mark_job_completed(job)
                db.commit()
                return _serialize_job(job)

            batch_size = min(settings.graph_backfill_batch_size, remaining)
            items = _fetch_batch_items(
                db,
                after_item_id=job.last_item_id or 0,
                batch_size=batch_size,
            )
            if not items:
                _mark_job_completed(job)
                db.commit()
                return _serialize_job(job)

            sources_map, keywords_by_item = _load_batch_context(db, items)
            existing_ids = get_existing_market_article_ids([item.id for item in items])

            for item in items:
                try:
                    if item.id in existing_ids:
                        job.processed_items += 1
                        job.synced_items += 1
                        job.last_item_id = item.id
                        db.commit()
                        continue

                    ok = sync_market_article(
                        item,
                        sources_map.get(item.source_id),
                        keywords_by_item.get(item.id, []),
                        raise_on_rate_limit=True,
                    )
                    job.processed_items += 1
                    job.last_item_id = item.id
                    if ok:
                        job.synced_items += 1
                    else:
                        job.failed_items += 1
                        job.error_message = "market_articles_collection_unavailable"
                    db.commit()
                except MarketEntityRateLimitedError as exc:
                    retry_after = max(exc.retry_after_seconds, 5.0)
                    job.status = "paused"
                    job.paused_until = now + timedelta(seconds=retry_after)
                    job.error_message = f"rate_limited_retry_after={retry_after:.2f}s"
                    db.commit()
                    return _serialize_job(job)
                except Exception as exc:
                    logger.exception("Failed to sync market backfill item_id=%s", item.id)
                    job.processed_items += 1
                    job.failed_items += 1
                    job.last_item_id = item.id
                    job.error_message = f"item_id={item.id}:{type(exc).__name__}"
                    db.commit()

            db.refresh(job)


def resume_pending_market_backfill_jobs() -> list[dict]:
    with SessionLocal() as db:
        jobs = db.execute(
            select(Job)
            .where(
                Job.job_type == MARKET_GRAPH_BACKFILL_JOB_TYPE,
                Job.status.in_(ACTIVE_MARKET_GRAPH_BACKFILL_STATUSES),
            )
            .order_by(Job.id.asc())
        ).scalars().all()
        return [_serialize_job(job) for job in jobs]
