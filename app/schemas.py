from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class Slot(str, Enum):
    am = "am"
    pm = "pm"


class FeedItemOut(BaseModel):
    item_id: int
    title: str
    translated_title_ko: str | None = None
    source: str
    category: str
    url: str
    short_reason: str
    rank: int
    saved: bool
    skipped: bool
    liked: bool
    disliked: bool
    curation_action: str | None = None
    preference_action: str | None = None
    feedback_action: str | None = None


class FeedCategoryGroup(BaseModel):
    category: str
    items: list[FeedItemOut]


class FeedOut(BaseModel):
    feed_date: str
    slot: Slot
    generated_at: datetime
    items: list[FeedItemOut]
    groups: list[FeedCategoryGroup] = []


class FeedbackIn(BaseModel):
    item_id: int
    action: str


class ClickEventIn(BaseModel):
    item_id: int


class MetricsOut(BaseModel):
    date_from: str
    date_to: str
    impressions: int
    clicks: int
    generated_slots: int
    opened_slots: int
    ctr: float
    slot_open_rate: float


class HealthOut(BaseModel):
    status: str
    db: str
