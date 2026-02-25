from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Request

from app.db import get_db
from app.models import ItemEventType, User
from app.schemas import ClickEventIn
from app.security import get_optional_user
from app.services.events import create_item_event

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/click", status_code=201)
def create_click_event(
    payload: ClickEventIn,
    user: User | None = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    try:
        row = create_item_event(db, payload.item_id, ItemEventType.CLICK.value, user_id=user.id if user else None)
    except ValueError:
        raise HTTPException(status_code=404, detail="item_not_found") from None

    db.commit()
    return {"ok": True, "event_id": row.id}
