from math import ceil

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_db
from app.models import Feedback, FeedbackAction, Item, Source
from app.schemas import BookmarkAskIn, BookmarkAskOut, BookmarkSource, KeywordCloudItem, KeywordCloudOut, KeywordGraphOut, KeywordNeighbor
from app.services.events import CURATION_ACTIONS
from app.services.graph import get_keyword_graph, get_bookmark_keyword_cloud
from app.services.rag import ask_bookmarks

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get("")
def get_bookmarks(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    latest_feedback = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(Feedback.action.in_(list(CURATION_ACTIONS)))
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
def bookmark_ask(payload: BookmarkAskIn):
    result = ask_bookmarks(payload.query, payload.top_k)
    return BookmarkAskOut(
        answer=result["answer"],
        sources=[BookmarkSource(**s) for s in result.get("sources", [])],
    )


@router.get("/explore", response_model=KeywordGraphOut)
def bookmark_explore(
    keyword: str = Query(..., min_length=1),
    depth: int = Query(default=1, ge=1, le=3),
):
    result = get_keyword_graph(keyword, depth)
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
def bookmark_keywords(limit: int = Query(default=30, ge=1, le=100)):
    results = get_bookmark_keyword_cloud(limit)
    items = [KeywordCloudItem(**r) for r in results]
    return KeywordCloudOut(total=len(items), keywords=items)
