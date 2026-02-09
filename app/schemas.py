from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class Slot(str, Enum):
    am = "am"
    pm = "pm"


class FeedItemOut(BaseModel):
    item_id: int
    title: str
    source: str
    url: str
    short_reason: str
    rank: int
    saved: bool


class FeedOut(BaseModel):
    feed_date: str
    slot: Slot
    generated_at: datetime
    items: list[FeedItemOut]


class FeedbackIn(BaseModel):
    item_id: int
    action: str


class HealthOut(BaseModel):
    status: str
    db: str
