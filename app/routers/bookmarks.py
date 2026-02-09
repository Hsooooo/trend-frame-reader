from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.db import get_db
from app.models import Feedback, FeedbackAction, Item, Source

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("")
def get_bookmarks(db: Session = Depends(get_db)):
    latest_feedback = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .group_by(Feedback.item_id)
        .subquery()
    )

    rows = db.execute(
        select(Item, Source)
        .join(latest_feedback, latest_feedback.c.item_id == Item.id)
        .join(Feedback, Feedback.id == latest_feedback.c.max_id)
        .join(Source, Item.source_id == Source.id)
        .where(Feedback.action == FeedbackAction.SAVED)
        .order_by(Item.id.desc())
    ).all()

    return {
        "items": [
            {
                "item_id": item.id,
                "title": item.title,
                "url": item.url,
                "source": source.name,
                "saved": True,
            }
            for item, source in rows
        ]
    }
