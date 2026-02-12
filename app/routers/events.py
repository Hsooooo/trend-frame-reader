from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException

from app.db import get_db
from app.models import ItemEventType
from app.schemas import ClickEventIn
from app.services.events import create_item_event

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/click", status_code=201)
def create_click_event(payload: ClickEventIn, db: Session = Depends(get_db)):
    try:
        row = create_item_event(db, payload.item_id, ItemEventType.CLICK.value)
    except ValueError:
        raise HTTPException(status_code=404, detail="item_not_found") from None

    db.commit()
    return {"ok": True, "event_id": row.id}
