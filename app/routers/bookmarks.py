from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Query

from app.db import get_db
from app.models import Feedback, FeedbackAction, Item, Source

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("")
def get_bookmarks(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    latest_feedback = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .group_by(Feedback.item_id)
        .subquery()
    )

    base_query = (
        select(Item, Source, Feedback.created_at)
        .join(latest_feedback, latest_feedback.c.item_id == Item.id)
        .join(Feedback, Feedback.id == latest_feedback.c.max_id)
        .join(Source, Item.source_id == Source.id)
        .where(Feedback.action == FeedbackAction.SAVED)
        .order_by(Feedback.created_at.desc(), Item.id.desc())
    )

    total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar_one()
    total_pages = ceil(total / size) if total > 0 else 0
    offset = (page - 1) * size

    rows = db.execute(base_query.offset(offset).limit(size)).all()

    return {
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total > 0,
        "items": [
            {
                "item_id": item.id,
                "title": item.title,
                "url": item.url,
                "source": source.name,
                "saved": True,
                "saved_at": saved_at,
            }
            for item, source, saved_at in rows
        ]
    }
