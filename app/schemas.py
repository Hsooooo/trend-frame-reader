from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


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


class RssPublishedAtBackfillIn(BaseModel):
    start_date: date = Field(default=date(2026, 2, 20))
    end_date: date | None = None
    limit_per_source: int = Field(default=300, ge=10, le=2000)
    only_null_published_at: bool = True
    dry_run: bool = False


class RssPublishedAtBackfillOut(BaseModel):
    start_date: str
    end_date: str
    sources_total: int
    sources_processed: int
    source_errors: int
    entries_scanned: int
    matched_items: int
    updated_items: int
    skipped_missing_datetime: int
    dry_run: bool


class HealthOut(BaseModel):
    status: str
    db: str


class BookmarkAskIn(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)


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


class MarketGraphBackfillOut(BaseModel):
    processed: int
    synced: int
    failed: int
    status: str


class FullGraphKeywordNode(BaseModel):
    id: str                    # "kw_{keyword}"
    keyword: str
    doc_frequency: int = 0
    bookmark_frequency: int = 0
    sentiment_score: float = 0.0

class FullGraphArticleNode(BaseModel):
    id: str                    # "item_{item_id}"
    item_id: int
    title: str
    url: str
    source: str | None = None
    saved_at: str | None = None
    keywords: list[str] = []

class GraphEdge(BaseModel):
    source: str
    target: str
    type: str                  # "cooccurrence" | "has_keyword"
    weight: int = 1

class FullGraphOut(BaseModel):
    keyword_nodes: list[FullGraphKeywordNode]
    article_nodes: list[FullGraphArticleNode]
    edges: list[GraphEdge]

class TimelineArticle(BaseModel):
    item_id: int
    title: str
    url: str
    source: str | None = None
    saved_at: str
    keywords: list[str] = []
    sentiment: str | None = None

class TimelineOut(BaseModel):
    articles: list[TimelineArticle]


class MarketTickerNode(BaseModel):
    id: str
    symbol: str
    exchange: str | None = None
    mention_count: int = 0
    is_focus: bool = False


class MarketCompanyNode(BaseModel):
    id: str
    canonical_name: str
    mention_count: int = 0


class MarketEventNode(BaseModel):
    id: str
    event_type: str
    label: str
    count: int = 0


class MarketThemeNode(BaseModel):
    id: str
    name: str
    count: int = 0


class MarketArticleNode(BaseModel):
    id: str
    item_id: int
    title: str
    url: str
    source: str | None = None
    published_at: str | None = None
    companies: list[str] = []
    tickers: list[str] = []
    events: list[str] = []
    themes: list[str] = []


class MarketGraphEdge(BaseModel):
    source: str
    target: str
    type: str
    weight: int = 1


class MarketTickerGraphOut(BaseModel):
    focus_ticker: str
    ticker_nodes: list[MarketTickerNode]
    company_nodes: list[MarketCompanyNode]
    event_nodes: list[MarketEventNode]
    theme_nodes: list[MarketThemeNode]
    article_nodes: list[MarketArticleNode]
    edges: list[MarketGraphEdge]


class InsightPostOut(BaseModel):
    slug: str
    title: str
    summary: str | None = None
    body: str | None = None
    period_start: str
    period_end: str
    published_at: datetime | None = None


class InsightPostAdminOut(BaseModel):
    id: int
    slug: str
    title: str
    summary: str | None = None
    body: str | None = None
    status: str
    period_start: str
    period_end: str
    created_at: datetime
    published_at: datetime | None = None


class InsightDraftIn(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


class InsightPatchIn(BaseModel):
    title: str | None = None
    summary: str | None = None
    body: str | None = None


class InsightListOut(BaseModel):
    total: int
    posts: list[InsightPostOut]


class InsightAdminListOut(BaseModel):
    total: int
    posts: list[InsightPostAdminOut]


class SimilarityGraphKeywordNode(BaseModel):
    id: str                       # "kw_{keyword}"
    keyword: str
    doc_frequency: int = 0
    bookmark_frequency: int = 0
    sentiment_score: float = 0.0
    similarity_score: float = 1.0  # 루트=1.0, 나머지=코사인 유사도
    is_root: bool = False


class SimilarityGraphEdge(BaseModel):
    source: str
    target: str
    type: str                     # "similarity" | "has_keyword"
    weight: float = 1.0           # similarity: 0~1 float, has_keyword: 1.0


class SimilarityGraphOut(BaseModel):
    root_keyword: str
    keyword_nodes: list[SimilarityGraphKeywordNode]
    article_nodes: list[FullGraphArticleNode]
    edges: list[SimilarityGraphEdge]


class UserStatItem(BaseModel):
    user_id: int
    email: str
    name: str
    is_owner: bool
    joined_at: str
    impressions: int = 0
    clicks: int = 0
    ctr: float = 0.0
    saved: int = 0
    liked: int = 0
    disliked: int = 0
    skipped: int = 0


class UserStatsOut(BaseModel):
    date_from: str
    date_to: str
    users: list[UserStatItem]
