from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends

from app.db import get_db
from app.schemas import HealthOut

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthOut)
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return HealthOut(status="ok", db="ok")
