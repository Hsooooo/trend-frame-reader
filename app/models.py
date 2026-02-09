from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import Date, DateTime, Enum as SQLEnum, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class SourceType(str, Enum):
    RSS = "rss"
    HN = "hn"


class FeedbackAction(str, Enum):
    SAVED = "saved"
    SKIPPED = "skipped"


class SlotType(str, Enum):
    AM = "am"
    PM = "pm"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[SourceType] = mapped_column(SQLEnum(SourceType), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="en", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    source: Mapped[Source] = relationship()


class Feed(Base):
    __tablename__ = "feeds"
    __table_args__ = (UniqueConstraint("feed_date", "slot", name="uq_feed_date_slot"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_date: Mapped[datetime.date] = mapped_column(Date, nullable=False)
    slot: Mapped[SlotType] = mapped_column(SQLEnum(SlotType), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class FeedItem(Base):
    __tablename__ = "feed_items"
    __table_args__ = (UniqueConstraint("feed_id", "item_id", name="uq_feed_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    feed_id: Mapped[int] = mapped_column(ForeignKey("feeds.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    short_reason: Mapped[str] = mapped_column(String(255), nullable=False)


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), nullable=False)
    action: Mapped[FeedbackAction] = mapped_column(SQLEnum(FeedbackAction), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
