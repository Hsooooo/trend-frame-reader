from sqlalchemy import select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models import Feedback, FeedbackAction, Item
from app.schemas import FeedbackIn

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=201)
def create_feedback(payload: FeedbackIn, db: Session = Depends(get_db)):
    item_exists = db.execute(select(Item.id).where(Item.id == payload.item_id)).scalar_one_or_none()
    if not item_exists:
        raise HTTPException(status_code=404, detail="item_not_found")

    if payload.action not in {FeedbackAction.SAVED.value, FeedbackAction.SKIPPED.value}:
        raise HTTPException(status_code=400, detail="invalid_action")

    row = Feedback(item_id=payload.item_id, action=FeedbackAction(payload.action))
    db.add(row)
    db.commit()
    return {"ok": True, "feedback_id": row.id}
