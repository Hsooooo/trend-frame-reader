from __future__ import annotations

import calendar
import difflib
import logging
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Item, ItemKeyword, Job, Source, SourceType
from app.services.feed_catalog import STOCK_FEED_CATEGORIES
from app.services.market_graph import sync_market_article
from app.services.keywords import extract_keywords, build_keyword_text
from app.services.ranking import compute_score
from app.services.translation import translate_title_to_korean
from app.services.utils import canonicalize_url, detect_language, title_key, utcnow

logger = logging.getLogger(__name__)


def _sort_feed_candidates(candidates: list[tuple[Source, dict]]) -> list[tuple[Source, dict]]:
    def sort_key(row: tuple[Source, dict]) -> tuple[datetime, str]:
        _, payload = row
        published_at = payload.get("published_at")
        if not isinstance(published_at, datetime):
            published_at = datetime.min.replace(tzinfo=UTC)
        return published_at, payload.get("title") or ""

    return sorted(candidates, key=sort_key, reverse=True)


def _fetch_source_items(source: Source, *, limit: int | None = None) -> list[dict]:
    if source.type == SourceType.HN:
        return _fetch_hn_items(limit=limit or 80)
    if source.type == SourceType.ALPACA_NEWS:
        fetch_limit = limit or settings.alpaca_news_limit_per_source
        return _fetch_alpaca_news_items(source.url, limit=fetch_limit)
    return _fetch_rss_items(source.url, limit=limit or 50)


def _insert_ingested_item(
    db: Session,
    *,
    source: Source,
    obj: dict,
    seen_canonical: set[str],
) -> bool:
    canonical = canonicalize_url(obj["url"])
    if canonical in seen_canonical:
        return False

    existing = db.execute(select(Item).where(Item.canonical_url == canonical)).scalar_one_or_none()
    if existing:
        _refresh_existing_item(db, item=existing, source=source, obj=obj)
        seen_canonical.add(canonical)
        return False

    if _is_similar_title(db, obj["title"]):
        return False

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
        summary=obj.get("summary"),
        published_at=obj.get("published_at"),
        fetched_at=utcnow(),
        language=language,
        dedupe_key=title_key(obj["title"]),
        score=compute_score(source.weight, obj.get("published_at"), points=obj.get("points")),
    )
    db.add(item)
    db.flush()

    kw_text = build_keyword_text(obj["title"], obj.get("summary"))
    extracted_keywords = extract_keywords(kw_text, title=obj["title"], summary=obj.get("summary"))
    for kw in extracted_keywords:
        db.add(ItemKeyword(
            item_id=item.id,
            keyword=kw["keyword"],
            relevance_score=kw["score"],
        ))
    db.flush()

    try:
        sync_market_article(item, source, [kw["keyword"] for kw in extracted_keywords])
    except Exception:
        logger.warning("market graph sync failed for item_id=%s", item.id, exc_info=True)

    seen_canonical.add(canonical)
    return True


def _refresh_existing_item(
    db: Session,
    *,
    item: Item,
    source: Source,
    obj: dict,
) -> None:
    updated = False

    if not item.summary and obj.get("summary"):
        item.summary = obj["summary"]
        updated = True

    published_at = obj.get("published_at")
    if item.published_at is None and published_at is not None:
        item.published_at = published_at
        item.score = compute_score(source.weight, published_at, points=obj.get("points"))
        updated = True

    if item.language != "ko" and not item.translated_title_ko:
        translated_title_ko = translate_title_to_korean(item.title)
        if translated_title_ko:
            item.translated_title_ko = translated_title_ko
            updated = True

    if not updated:
        return

    keywords = db.execute(
        select(ItemKeyword.keyword)
        .where(ItemKeyword.item_id == item.id)
        .order_by(ItemKeyword.relevance_score.asc(), ItemKeyword.id.asc())
    ).scalars().all()
    try:
        sync_market_article(item, source, list(keywords))
    except Exception:
        logger.warning("market graph sync failed for existing item_id=%s", item.id, exc_info=True)


def _parse_hn_ts(ts: str | None):
    if not ts:
        return None
    # Example: 2026-02-09T02:41:00Z
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _parse_iso_ts(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        return None


def _parse_feed_entry_ts(entry) -> datetime | None:
    """Parse entry timestamp from feedparser entry with sensible fallbacks."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, key, None)
        if parsed:
            try:
                return datetime.fromtimestamp(calendar.timegm(parsed), tz=UTC)
            except Exception:
                continue

    for key in ("published", "updated"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except Exception:
            continue
    return None


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
        out.append({
            "title": title,
            "url": link,
            "published_at": _parse_hn_ts(h.get("created_at")),
            "points": h.get("points") or 0,
        })
    return out


def _strip_html(text: str) -> str:
    import html as _html
    import re
    # Remove HTML tags first, then decode entities (&amp; → &, &lt; → <, etc.)
    stripped = re.sub(r"<[^>]+>", "", text)
    return _html.unescape(stripped).strip()


def _fetch_rss_items(url: str, limit: int = 50) -> list[dict]:
    try:
        response = httpx.get(
            url,
            timeout=settings.rss_fetch_timeout_seconds,
            follow_redirects=True,
            headers={
                "User-Agent": settings.rss_fetch_user_agent,
                "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
            },
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
    except httpx.HTTPError:
        logger.warning("rss_source_http_fetch_failed: url=%s", url, exc_info=True)
        feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:limit]:
        link = e.get("link")
        title = e.get("title")
        if not link or not title:
            continue
        summary_raw = e.get("summary", "") or ""
        summary = _strip_html(summary_raw) if summary_raw else None
        out.append({
            "title": title,
            "url": link,
            "published_at": _parse_feed_entry_ts(e),
            "summary": summary,
        })
    return out


def _fetch_alpaca_news_items(url: str, limit: int = 50) -> list[dict]:
    if not settings.alpaca_api_key_id or not settings.alpaca_api_secret_key:
        logger.info("alpaca_news_skipped_missing_credentials")
        return []

    response = httpx.get(
        url,
        timeout=settings.rss_fetch_timeout_seconds,
        headers={
            "APCA-API-KEY-ID": settings.alpaca_api_key_id,
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret_key,
            "Accept": "application/json",
            "User-Agent": settings.rss_fetch_user_agent,
        },
        params={
            "limit": min(limit, settings.alpaca_news_limit_per_source),
            "sort": "desc",
        },
    )
    response.raise_for_status()
    payload = response.json()
    articles = payload.get("news", []) if isinstance(payload, dict) else []

    out = []
    for article in articles[:limit]:
        title = article.get("headline")
        link = article.get("url")
        if not title or not link:
            continue

        summary_parts: list[str] = []
        summary = (article.get("summary") or "").strip()
        if summary:
            summary_parts.append(summary)
        symbols = [symbol.strip().upper() for symbol in article.get("symbols", []) if isinstance(symbol, str) and symbol.strip()]
        if symbols:
            summary_parts.append(f"Related symbols: {', '.join(symbols[:10])}")
        author = (article.get("author") or "").strip()
        publisher = (article.get("source") or "").strip()
        attribution = " · ".join(part for part in (publisher, author) if part)
        if attribution:
            summary_parts.append(attribution)

        out.append({
            "title": title,
            "url": link,
            "published_at": _parse_iso_ts(article.get("created_at")) or _parse_iso_ts(article.get("updated_at")),
            "summary": " ".join(summary_parts).strip() or None,
        })

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


def backfill_rss_published_at(
    db: Session,
    start_date: date,
    end_date: date | None = None,
    limit_per_source: int = 300,
    only_null_published_at: bool = True,
    dry_run: bool = False,
) -> dict:
    """Backfill published_at for RSS items in a fetched_at date window."""
    if end_date is None:
        end_date = datetime.now(UTC).date()
    if start_date > end_date:
        raise ValueError("invalid_date_range")

    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    sources = db.execute(
        select(Source).where(Source.type == SourceType.RSS, Source.enabled == True)  # noqa: E712
    ).scalars().all()

    sources_processed = 0
    source_errors = 0
    entries_scanned = 0
    matched_items = 0
    updated_items = 0
    skipped_missing_datetime = 0

    for source in sources:
        try:
            source_entries = _fetch_rss_items(source.url, limit=limit_per_source)
        except Exception:
            logger.warning("rss_backfill_source_fetch_failed: source_id=%s", source.id, exc_info=True)
            source_errors += 1
            continue

        sources_processed += 1
        for obj in source_entries:
            entries_scanned += 1
            published_at = obj.get("published_at")
            if published_at is None:
                skipped_missing_datetime += 1
                continue

            canonical = canonicalize_url(obj["url"])

            stmt = (
                select(Item)
                .where(
                    Item.source_id == source.id,
                    Item.canonical_url == canonical,
                    Item.fetched_at >= start_dt,
                    Item.fetched_at < end_dt,
                )
                .order_by(Item.id.desc())
            )
            if only_null_published_at:
                stmt = stmt.where(Item.published_at.is_(None))
            item = db.execute(stmt).scalars().first()

            # Fallback to raw URL matching for rare canonicalization mismatches.
            if item is None:
                stmt_fallback = (
                    select(Item)
                    .where(
                        Item.source_id == source.id,
                        Item.url == obj["url"],
                        Item.fetched_at >= start_dt,
                        Item.fetched_at < end_dt,
                    )
                    .order_by(Item.id.desc())
                )
                if only_null_published_at:
                    stmt_fallback = stmt_fallback.where(Item.published_at.is_(None))
                item = db.execute(stmt_fallback).scalars().first()

            if item is None:
                continue

            matched_items += 1
            if item.published_at == published_at:
                continue

            if dry_run:
                updated_items += 1
                continue

            item.published_at = published_at
            updated_items += 1

    if not dry_run:
        db.commit()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources_total": len(sources),
        "sources_processed": sources_processed,
        "source_errors": source_errors,
        "entries_scanned": entries_scanned,
        "matched_items": matched_items,
        "updated_items": updated_items,
        "skipped_missing_datetime": skipped_missing_datetime,
        "dry_run": dry_run,
    }


def run_ingestion(
    db: Session,
    *,
    stock_only: bool = False,
    limit: int | None = None,
) -> dict:
    effective_limit = 20 if stock_only and (limit is None or limit <= 0) else limit
    started = utcnow()
    job = Job(
        job_type="ingestion_stock" if stock_only else "ingestion",
        started_at=started,
        status="running",
    )
    db.add(job)
    db.flush()

    inserted = 0
    scanned = 0
    sources_processed = 0
    source_errors = 0
    seen_canonical: set[str] = set()

    try:
        stmt = select(Source).where(Source.enabled == True)  # noqa: E712
        if stock_only:
            stmt = stmt.where(Source.category.in_(tuple(STOCK_FEED_CATEGORIES)))
        sources = db.execute(stmt.order_by(Source.id.asc())).scalars().all()

        if stock_only:
            fetch_limit = max(20, (effective_limit or 20) * 2)
            candidates: list[tuple[Source, dict]] = []
            processed_sources: list[Source] = []
            for source in sources:
                try:
                    items = _fetch_source_items(source, limit=fetch_limit)
                except Exception:
                    source_errors += 1
                    logger.warning("ingestion_source_fetch_failed: source_id=%s", source.id, exc_info=True)
                    continue
                sources_processed += 1
                processed_sources.append(source)
                candidates.extend((source, obj) for obj in items)

            for source, obj in _sort_feed_candidates(candidates):
                scanned += 1
                if _insert_ingested_item(db, source=source, obj=obj, seen_canonical=seen_canonical):
                    inserted += 1
                    if effective_limit is not None and effective_limit > 0 and inserted >= effective_limit:
                        break

            fetched_at = utcnow()
            for source in processed_sources:
                source.last_fetched_at = fetched_at
        else:
            for source in sources:
                try:
                    items = _fetch_source_items(source)
                except Exception:
                    source_errors += 1
                    logger.warning("ingestion_source_fetch_failed: source_id=%s", source.id, exc_info=True)
                    continue

                sources_processed += 1

                for obj in items:
                    scanned += 1
                    if _insert_ingested_item(db, source=source, obj=obj, seen_canonical=seen_canonical):
                        inserted += 1

                source.last_fetched_at = utcnow()

        job.status = "success"
        job.ended_at = utcnow()
        db.commit()
        return {
            "scanned": scanned,
            "inserted": inserted,
            "sources_processed": sources_processed,
            "source_errors": source_errors,
            "stock_only": stock_only,
            "limit": effective_limit,
        }
    except Exception as exc:
        db.rollback()
        job.status = "failed"
        job.error_message = str(exc)
        job.ended_at = utcnow()
        db.add(job)
        db.commit()
        raise
