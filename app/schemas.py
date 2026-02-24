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
    keywords: list[str] = []


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


class KeywordSentimentItem(BaseModel):
    keyword: str
    liked_count: int
    disliked_count: int
    total_items: int
    sentiment_score: float
    sentiment_label: str


class KeywordSentimentsOut(BaseModel):
    date_from: str
    date_to: str
    total_keywords: int
    keywords: list[KeywordSentimentItem]


class BackfillResultOut(BaseModel):
    processed: int
    keywords_created: int


class HealthOut(BaseModel):
    status: str
    db: str


class BookmarkAskIn(BaseModel):
    query: str
    top_k: int = 5


class BookmarkSource(BaseModel):
    item_id: int
    title: str
    url: str
    similarity: float


class BookmarkAskOut(BaseModel):
    answer: str
    sources: list[BookmarkSource]


class KeywordNeighbor(BaseModel):
    keyword: str
    count: int
    doc_frequency: int = 0


class KeywordGraphOut(BaseModel):
    keyword: str
    doc_frequency: int = 0
    bookmark_frequency: int = 0
    sentiment_score: float = 0.0
    neighbors: list[KeywordNeighbor]


class KeywordCloudItem(BaseModel):
    keyword: str
    frequency: int
    sentiment_score: float = 0.0


class KeywordCloudOut(BaseModel):
    total: int
    keywords: list[KeywordCloudItem]


class GraphBackfillOut(BaseModel):
    items_processed: int
    status: str
