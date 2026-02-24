import logging

from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.schemas import FeedbackIn
from app.services.events import ALL_FEEDBACK_ACTIONS, create_feedback_with_context

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/feedback", tags=["feedback"])


@router.post("", status_code=201)
def create_feedback(payload: FeedbackIn, db: Session = Depends(get_db)):
    if payload.action not in ALL_FEEDBACK_ACTIONS:
        raise HTTPException(status_code=400, detail="invalid_action")

    try:
        row = create_feedback_with_context(db, payload.item_id, payload.action)
    except ValueError:
        raise HTTPException(status_code=404, detail="item_not_found") from None

    db.commit()
    if payload.action in ("saved", "liked", "disliked"):
        try:
            from app.services.graph import sync_bookmark_to_graph
            sync_bookmark_to_graph(db, payload.item_id, payload.action)
        except Exception:
            logger.warning("graph sync failed for item %s", payload.item_id, exc_info=True)
    return {"ok": True, "feedback_id": row.id}
