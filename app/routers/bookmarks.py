from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.models import Feedback, FeedbackAction, Item, Source, User
from app.schemas import (
    BookmarkAskIn,
    BookmarkAskOut,
    BookmarkSource,
    FullGraphArticleNode,
    FullGraphKeywordNode,
    FullGraphOut,
    GraphEdge,
    KeywordCloudItem,
    KeywordCloudOut,
    KeywordGraphOut,
    KeywordNeighbor,
    SimilarityGraphOut,
    TimelineArticle,
    TimelineOut,
)
from app.security import get_current_user
from app.services.events import CURATION_ACTIONS
from app.services.graph import get_bookmark_keyword_cloud, get_full_graph, get_keyword_graph, get_similarity_graph, get_timeline_articles
from app.services.rag import ask_bookmarks

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("")
def get_bookmarks(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    latest_feedback = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(
            Feedback.action.in_(list(CURATION_ACTIONS)),
            Feedback.user_id == user.id,
        )
        .group_by(Feedback.item_id)
        .subquery()
    )

    base_query = (
        select(Item, Source, Feedback.created_at)
        .join(latest_feedback, latest_feedback.c.item_id == Item.id)
        .join(Feedback, Feedback.id == latest_feedback.c.max_id)
        .join(Source, Item.source_id == Source.id)
        .where(Feedback.action == FeedbackAction.SAVED.value)
        .order_by(Feedback.created_at.desc(), Item.id.desc())
    )

    total = db.execute(select(func.count()).select_from(base_query.subquery())).scalar_one()
    total_pages = ceil(total / size) if total > 0 else 0
    offset = (page - 1) * size

    rows = db.execute(base_query.offset(offset).limit(size)).all()

    return {
        "page": page,
        "size": size,
        "total": total,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1 and total > 0,
        "items": [
            {
                "item_id": item.id,
                "title": item.title,
                "url": item.url,
                "source": source.name,
                "saved": True,
                "saved_at": saved_at,
            }
            for item, source, saved_at in rows
        ]
    }


@router.post("/ask", response_model=BookmarkAskOut)
def bookmark_ask(
    payload: BookmarkAskIn,
    user: User = Depends(get_current_user),
):
    result = ask_bookmarks(payload.query, payload.top_k, user_id=user.id)
    return BookmarkAskOut(
        answer=result["answer"],
        sources=[BookmarkSource(**s) for s in result.get("sources", [])],
    )


@router.get("/explore", response_model=KeywordGraphOut)
def bookmark_explore(
    keyword: str = Query(..., min_length=1),
    depth: int = Query(default=1, ge=1, le=3),
    user: User = Depends(get_current_user),
):
    result = get_keyword_graph(keyword, depth, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail="keyword_not_found")
    return KeywordGraphOut(
        keyword=result["keyword"],
        doc_frequency=result.get("doc_frequency", 0),
        bookmark_frequency=result.get("bookmark_frequency", 0),
        sentiment_score=result.get("sentiment_score", 0.0),
        neighbors=[KeywordNeighbor(**n) for n in result.get("neighbors", [])],
    )


@router.get("/keywords", response_model=KeywordCloudOut)
def bookmark_keywords(
    limit: int = Query(default=30, ge=1, le=100),
    user: User = Depends(get_current_user),
):
    results = get_bookmark_keyword_cloud(limit, user_id=user.id)
    items = [KeywordCloudItem(**r) for r in results]
    return KeywordCloudOut(total=len(items), keywords=items)


@router.get("/graph", response_model=FullGraphOut)
def bookmark_graph(
    keyword: str = Query(..., min_length=1),
    depth: int = Query(default=1, ge=1, le=3),
    max_keyword_nodes: int = Query(default=0, ge=0, le=100),
    max_articles_per_keyword: int = Query(default=8, ge=1, le=20),
    user: User = Depends(get_current_user),
):
    result = get_full_graph(keyword, depth, max_keyword_nodes, max_articles_per_keyword, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail="keyword_not_found")
    return FullGraphOut(
        keyword_nodes=[FullGraphKeywordNode(**n) for n in result.get("keyword_nodes", [])],
        article_nodes=[FullGraphArticleNode(**n) for n in result.get("article_nodes", [])],
        edges=[GraphEdge(**e) for e in result.get("edges", [])],
    )


@router.get("/graph/similarity", response_model=SimilarityGraphOut)
def bookmark_similarity_graph(
    keyword: str = Query(..., min_length=1),
    threshold: float = Query(default=0.5, ge=0.0, le=1.0),
    limit: int = Query(default=15, ge=1, le=50),
    max_articles_per_keyword: int = Query(default=3, ge=1, le=10),
    user: User = Depends(get_current_user),
):
    result = get_similarity_graph(keyword, threshold, limit, max_articles_per_keyword, user_id=user.id)
    if not result:
        raise HTTPException(status_code=404, detail="keyword_not_found")
    return result


@router.get("/timeline", response_model=TimelineOut)
def bookmark_timeline(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(get_current_user),
):
    articles = get_timeline_articles(days, user_id=user.id)
    return TimelineOut(
        articles=[TimelineArticle(**a) for a in articles],
    )
