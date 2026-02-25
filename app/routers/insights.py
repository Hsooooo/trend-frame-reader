from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from fastapi import Depends

from app.db import get_db
from app.models import InsightPost
from app.schemas import InsightListOut, InsightPostOut

router = APIRouter(prefix="/insights", tags=["insights"])


def _post_to_out(post: InsightPost) -> InsightPostOut:
    return InsightPostOut(
        slug=post.slug,
        title=post.title,
        summary=post.summary,
        body=post.body,
        period_start=str(post.period_start),
        period_end=str(post.period_end),
        published_at=post.published_at,
    )


@router.get("/posts", response_model=InsightListOut)
def list_published_posts(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    total = db.execute(
        select(InsightPost).where(InsightPost.status == "published")
    ).scalars().all()
    stmt = (
        select(InsightPost)
        .where(InsightPost.status == "published")
        .order_by(InsightPost.published_at.desc())
        .offset(offset)
        .limit(limit)
    )
    posts = db.execute(stmt).scalars().all()
    return InsightListOut(
        total=len(total),
        posts=[_post_to_out(p) for p in posts],
    )


@router.get("/posts/{slug}", response_model=InsightPostOut)
def get_published_post(slug: str, db: Session = Depends(get_db)):
    post = db.execute(
        select(InsightPost).where(
            InsightPost.slug == slug,
            InsightPost.status == "published",
        )
    ).scalar_one_or_none()
    if post is None:
        raise HTTPException(status_code=404, detail="post_not_found")
    return _post_to_out(post)
