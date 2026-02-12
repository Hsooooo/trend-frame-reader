from __future__ import annotations

import difflib

import feedparser
import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Item, Job, Source, SourceType
from app.services.ranking import compute_score
from app.services.translation import translate_title_to_korean
from app.services.utils import canonicalize_url, detect_language, title_key, utcnow


def _parse_hn_ts(ts: str | None):
    if not ts:
        return None
    # Example: 2026-02-09T02:41:00Z
    from datetime import datetime
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fetch_hn_items(limit: int = 80) -> list[dict]:
    url = "https://hn.algolia.com/api/v1/search_by_date?tags=story&numericFilters=points>20"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    hits = resp.json().get("hits", [])
    out = []
    for h in hits[:limit]:
        link = h.get("url")
        title = h.get("title")
        if not link or not title:
            continue
        out.append({"title": title, "url": link, "published_at": _parse_hn_ts(h.get("created_at"))})
    return out


def _fetch_rss_items(url: str, limit: int = 50) -> list[dict]:
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:limit]:
        link = e.get("link")
        title = e.get("title")
        if not link or not title:
            continue
        out.append({"title": title, "url": link, "published_at": None})
    return out


def _is_similar_title(db: Session, title: str) -> bool:
    cutoff = settings.title_similarity_threshold
    recent = db.execute(select(Item.title).order_by(desc(Item.id)).limit(500)).scalars().all()
    t = title.lower().strip()
    for r in recent:
        score = difflib.SequenceMatcher(a=t, b=r.lower().strip()).ratio()
        if score >= cutoff:
            return True
    return False


def run_ingestion(db: Session) -> dict:
    started = utcnow()
    job = Job(job_type="ingestion", started_at=started, status="running")
    db.add(job)
    db.flush()

    inserted = 0
    scanned = 0
    seen_canonical: set[str] = set()

    try:
        sources = db.execute(select(Source).where(Source.enabled == True)).scalars().all()  # noqa: E712
        for source in sources:
            if source.type == SourceType.HN:
                items = _fetch_hn_items()
            else:
                items = _fetch_rss_items(source.url)

            for obj in items:
                scanned += 1
                canonical = canonicalize_url(obj["url"])
                if canonical in seen_canonical:
                    continue
                exists = db.execute(select(Item.id).where(Item.canonical_url == canonical)).scalar_one_or_none()
                if exists:
                    continue

                if _is_similar_title(db, obj["title"]):
                    continue

                language = detect_language(obj["title"])
                translated_title_ko = None
                if language != "ko":
                    translated_title_ko = translate_title_to_korean(obj["title"])

                item = Item(
                    source_id=source.id,
                    canonical_url=canonical,
                    url=obj["url"],
                    title=obj["title"],
                    translated_title_ko=translated_title_ko,
                    published_at=obj.get("published_at"),
                    fetched_at=utcnow(),
                    language=language,
                    dedupe_key=title_key(obj["title"]),
                    score=compute_score(source.weight, obj.get("published_at")),
                )
                db.add(item)
                seen_canonical.add(canonical)
                inserted += 1

            source.last_fetched_at = utcnow()

        job.status = "success"
        job.ended_at = utcnow()
        db.commit()
        return {"scanned": scanned, "inserted": inserted}
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)
        job.ended_at = utcnow()
        db.add(job)
        db.commit()
        raise
