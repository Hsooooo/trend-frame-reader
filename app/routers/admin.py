from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import case, cast, Float as SAFloat, func, select, text
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import settings
from app.db import get_db
from app.models import Feedback, Feed, InsightPost, Item, ItemEvent, ItemEventType, ItemKeyword, User
from app.schemas import (
    BackfillResultOut,
    GraphBackfillOut,
    InsightAdminListOut,
    InsightDraftIn,
    InsightPatchIn,
    InsightPostAdminOut,
    KeywordSentimentItem,
    KeywordSentimentsOut,
    MetricsOut,
)
from app.services.graph import backfill_graph
from app.services.insights import generate_draft, publish_post, unpublish_post
from app.services.keyword_embeddings import backfill_keyword_embeddings
from app.mongo import get_keywords_collection
from app.security import get_current_user, require_owner
from app.services.keywords import build_keyword_text, extract_keywords

router = APIRouter(prefix="/admin", tags=["admin"])
APP_TZ = ZoneInfo(settings.app_timezone)


def _window_or_400(date_from: str | None, date_to: str | None) -> tuple[datetime, datetime, date, date]:
    try:
        to_date = date.fromisoformat(date_to) if date_to else datetime.now(APP_TZ).date()
        from_date = date.fromisoformat(date_from) if date_from else (to_date - timedelta(days=6))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_date_format") from None

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="invalid_date_range")

    start_local = datetime.combine(from_date, time.min, APP_TZ)
    end_local = datetime.combine(to_date + timedelta(days=1), time.min, APP_TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC), from_date, to_date


def _score_to_label(score: float, liked: int, disliked: int) -> str:
    if liked > 0 and disliked > 0 and abs(score) < 0.2:
        return "mixed"
    if score >= 0.5:
        return "very_positive"
    if score >= 0.1:
        return "positive"
    if score > -0.1:
        return "neutral"
    if score > -0.5:
        return "negative"
    return "very_negative"


@router.get("/metrics", response_model=MetricsOut)
def get_metrics(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    start_dt, end_dt, from_date, to_date = _window_or_400(date_from, date_to)

    impressions = db.execute(
        select(func.count())
        .select_from(ItemEvent)
        .where(
            ItemEvent.event_type == ItemEventType.IMPRESSION.value,
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
    ).scalar_one()
    clicks = db.execute(
        select(func.count())
        .select_from(ItemEvent)
        .where(
            ItemEvent.event_type == ItemEventType.CLICK.value,
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
    ).scalar_one()
    generated_slots = db.execute(
        select(func.count())
        .select_from(Feed)
        .where(
            Feed.generated_at >= start_dt,
            Feed.generated_at < end_dt,
        )
    ).scalar_one()
    opened_slots = db.execute(
        select(func.count(func.distinct(ItemEvent.feed_id)))
        .where(
            ItemEvent.event_type == ItemEventType.IMPRESSION.value,
            ItemEvent.feed_id.is_not(None),
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
    ).scalar_one()

    ctr = (clicks / impressions) if impressions > 0 else 0.0
    slot_open_rate = (opened_slots / generated_slots) if generated_slots > 0 else 0.0
    return MetricsOut(
        date_from=str(from_date),
        date_to=str(to_date),
        impressions=impressions,
        clicks=clicks,
        generated_slots=generated_slots,
        opened_slots=opened_slots,
        ctr=ctr,
        slot_open_rate=slot_open_rate,
    )


@router.get("/keyword-sentiments", response_model=KeywordSentimentsOut)
def get_keyword_sentiments(
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    min_feedback: int = Query(default=2, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    _: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_dt, end_dt, from_date, to_date = _window_or_400(date_from, date_to)

    liked_count = func.count(case((Feedback.action == "liked", 1)))
    disliked_count = func.count(case((Feedback.action == "disliked", 1)))
    total_feedback = func.count()
    total_items = func.count(func.distinct(ItemKeyword.item_id))

    stmt = (
        select(
            ItemKeyword.keyword,
            liked_count.label("liked_count"),
            disliked_count.label("disliked_count"),
            total_items.label("total_items"),
            total_feedback.label("total_feedback"),
        )
        .join(Feedback, Feedback.item_id == ItemKeyword.item_id)
        .where(
            Feedback.action.in_(["liked", "disliked"]),
            Feedback.created_at >= start_dt,
            Feedback.created_at < end_dt,
        )
        .group_by(ItemKeyword.keyword)
        .having(total_feedback >= min_feedback)
        .order_by(total_feedback.desc())
        .limit(limit)
    )

    rows = db.execute(stmt).all()

    keywords = []
    for row in rows:
        score = (row.liked_count - row.disliked_count) / row.total_feedback if row.total_feedback > 0 else 0.0
        label = _score_to_label(score, row.liked_count, row.disliked_count)
        keywords.append(
            KeywordSentimentItem(
                keyword=row.keyword,
                liked_count=row.liked_count,
                disliked_count=row.disliked_count,
                total_items=row.total_items,
                sentiment_score=round(score, 3),
                sentiment_label=label,
            )
        )

    return KeywordSentimentsOut(
        date_from=str(from_date),
        date_to=str(to_date),
        total_keywords=len(keywords),
        keywords=keywords,
    )


@router.post("/backfill-keywords", response_model=BackfillResultOut)
def backfill_keywords(
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Extract keywords for existing items that don't have any yet."""
    existing_item_ids = (
        select(func.distinct(ItemKeyword.item_id))
    )
    items = db.execute(
        select(Item)
        .where(Item.id.not_in(existing_item_ids))
        .order_by(Item.id)
    ).scalars().all()

    processed = 0
    keywords_created = 0
    for item in items:
        kw_text = build_keyword_text(item.title, item.summary)
        for kw in extract_keywords(kw_text):
            db.add(ItemKeyword(
                item_id=item.id,
                keyword=kw["keyword"],
                relevance_score=kw["score"],
            ))
            keywords_created += 1
        processed += 1

    db.commit()
    return BackfillResultOut(processed=processed, keywords_created=keywords_created)


@router.post("/backfill-graph", response_model=GraphBackfillOut)
def admin_backfill_graph(
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    """Backfill MongoDB knowledge graph from existing bookmarks."""
    result = backfill_graph(db)
    return GraphBackfillOut(**result)


def _post_to_admin_out(post: InsightPost) -> InsightPostAdminOut:
    return InsightPostAdminOut(
        id=post.id,
        slug=post.slug,
        title=post.title,
        summary=post.summary,
        body=post.body,
        status=post.status,
        period_start=str(post.period_start),
        period_end=str(post.period_end),
        created_at=post.created_at,
        published_at=post.published_at,
    )


@router.get("/insights/posts", response_model=InsightAdminListOut)
def admin_list_insight_posts(
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    posts = db.execute(
        select(InsightPost).order_by(InsightPost.created_at.desc())
    ).scalars().all()
    return InsightAdminListOut(
        total=len(posts),
        posts=[_post_to_admin_out(p) for p in posts],
    )


@router.post("/insights/draft", response_model=InsightPostAdminOut)
def admin_create_insight_draft(
    body: InsightDraftIn = InsightDraftIn(),
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    post = generate_draft(db, days=body.days)
    return _post_to_admin_out(post)


@router.patch("/insights/posts/{post_id}", response_model=InsightPostAdminOut)
def admin_patch_insight_post(
    post_id: int,
    patch: InsightPatchIn,
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    post = db.get(InsightPost, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="post_not_found")
    if patch.title is not None:
        post.title = patch.title
    if patch.summary is not None:
        post.summary = patch.summary
    if patch.body is not None:
        post.body = patch.body
    db.commit()
    db.refresh(post)
    return _post_to_admin_out(post)


@router.post("/insights/posts/{post_id}/publish", response_model=InsightPostAdminOut)
def admin_publish_insight_post(
    post_id: int,
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        post = publish_post(db, post_id)
    except ValueError as e:
        detail = str(e)
        status = 404 if detail == "post_not_found" else 400
        raise HTTPException(status_code=status, detail=detail)
    return _post_to_admin_out(post)


@router.post("/insights/posts/{post_id}/unpublish", response_model=InsightPostAdminOut)
def admin_unpublish_insight_post(
    post_id: int,
    _: User = Depends(require_owner),
    db: Session = Depends(get_db),
):
    try:
        post = unpublish_post(db, post_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return _post_to_admin_out(post)


@router.post("/keywords/backfill-embeddings")
def admin_backfill_keyword_embeddings(
    _: User = Depends(require_owner),
):
    keywords_col = get_keywords_collection()
    if keywords_col is None:
        raise HTTPException(status_code=503, detail="mongodb_not_configured")
    result = backfill_keyword_embeddings(keywords_col)
    return result
