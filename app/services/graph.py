from __future__ import annotations

import logging
from datetime import UTC, datetime
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Feedback, FeedbackAction, Item, ItemKeyword, Source
from app.mongo import (
    get_articles_collection,
    get_graph_sync_log_collection,
    get_keywords_collection,
)
from app.services.embeddings import (
    build_embedding_text,
    generate_embedding,
    generate_embeddings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _upsert_article(articles_col, doc: dict) -> None:
    article_id = doc["_id"]
    articles_col.update_one(
        {"_id": article_id},
        {"$set": doc},
        upsert=True,
    )


def _increment_keyword(keywords_col, keyword: str, now: datetime) -> None:
    keywords_col.update_one(
        {"keyword": keyword},
        {
            "$inc": {"doc_frequency": 1, "bookmark_frequency": 1},
            "$set": {"last_seen_at": now},
            "$setOnInsert": {
                "keyword": keyword,
                "sentiment_score": None,
                "cooccurrences": [],
            },
        },
        upsert=True,
    )


def _update_cooccurrence(keywords_col, kw_a: str, kw_b: str) -> None:
    """Increment co-occurrence count for kw_b in kw_a's cooccurrences array.

    Two-step: try $inc on existing array element; if not modified, $push new entry.
    """
    result = keywords_col.update_one(
        {"keyword": kw_a, "cooccurrences.keyword": kw_b},
        {"$inc": {"cooccurrences.$.count": 1}},
    )
    if result.modified_count == 0:
        keywords_col.update_one(
            {"keyword": kw_a},
            {"$push": {"cooccurrences": {"keyword": kw_b, "count": 1}}},
            upsert=True,
        )


def _sync_cooccurrences(keywords_col, keywords: list[str]) -> None:
    for kw_a, kw_b in combinations(keywords, 2):
        _update_cooccurrence(keywords_col, kw_a, kw_b)
        _update_cooccurrence(keywords_col, kw_b, kw_a)


def _recalculate_sentiment(articles_col, keywords_col, keywords: list[str]) -> None:
    """Recompute sentiment_score for each keyword based on all bookmarked articles."""
    for kw in keywords:
        cursor = articles_col.find(
            {"keywords": kw, "sentiment": {"$in": ["liked", "disliked"]}},
            {"sentiment": 1},
        )
        liked = 0
        disliked = 0
        for article in cursor:
            if article.get("sentiment") == "liked":
                liked += 1
            elif article.get("sentiment") == "disliked":
                disliked += 1
        total = liked + disliked
        score = (liked - disliked) / total if total > 0 else None
        keywords_col.update_one(
            {"keyword": kw},
            {"$set": {"sentiment_score": score}},
        )


def _fetch_item_with_relations(db: Session, item_id: int):
    """Return (Item, Source, list[keyword_str]) or raise ValueError."""
    item = db.get(Item, item_id)
    if item is None:
        raise ValueError(f"Item {item_id} not found")
    source = db.get(Source, item.source_id)
    kw_rows = db.execute(
        select(ItemKeyword).where(ItemKeyword.item_id == item_id)
    ).scalars().all()
    keywords = [row.keyword for row in kw_rows]
    return item, source, keywords


def _build_article_doc(item: Item, source: Source | None, keywords: list[str], saved_at: datetime) -> dict:
    return {
        "_id": f"item_{item.id}",
        "item_id": item.id,
        "url": item.url,
        "title": item.title,
        "source": source.name if source else None,
        "category": source.category if source else None,
        "published_at": item.published_at,
        "saved_at": saved_at,
        "summary": item.summary,
        "keywords": keywords,
        "sentiment": None,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sync_bookmark_to_graph(db: Session, item_id: int, action: str) -> None:
    """Incremental sync. Called after a Feedback row is committed."""
    articles_col = get_articles_collection()
    keywords_col = get_keywords_collection()

    if action == FeedbackAction.SAVED:
        if articles_col is None or keywords_col is None:
            logger.debug("MongoDB not configured — skipping graph sync for item %d", item_id)
            return

        try:
            item, source, keywords = _fetch_item_with_relations(db, item_id)
        except ValueError:
            logger.error("sync_bookmark_to_graph: item %d not found in PG", item_id)
            return

        now = datetime.now(UTC)
        doc = _build_article_doc(item, source, keywords, saved_at=now)

        # Generate embedding if summary is available
        embed_text = build_embedding_text(item.title, item.summary)
        if embed_text is not None:
            embedding = generate_embedding(embed_text)
            if embedding is not None:
                doc["embedding"] = embedding

        try:
            _upsert_article(articles_col, doc)
        except Exception:
            logger.exception("Failed to upsert article %d into MongoDB", item_id)
            return

        for kw in keywords:
            try:
                _increment_keyword(keywords_col, kw, now)
            except Exception:
                logger.exception("Failed to upsert keyword '%s'", kw)

        try:
            _sync_cooccurrences(keywords_col, keywords)
        except Exception:
            logger.exception("Failed to sync co-occurrences for item %d", item_id)

    elif action in (FeedbackAction.LIKED, FeedbackAction.DISLIKED):
        if articles_col is None or keywords_col is None:
            return

        article_id = f"item_{item_id}"
        try:
            articles_col.update_one(
                {"_id": article_id},
                {"$set": {"sentiment": action}},
            )
        except Exception:
            logger.exception("Failed to update sentiment for article %s", article_id)
            return

        # Recalculate keyword sentiment scores
        article_doc = articles_col.find_one({"_id": article_id}, {"keywords": 1})
        if article_doc:
            keywords = article_doc.get("keywords", [])
            try:
                _recalculate_sentiment(articles_col, keywords_col, keywords)
            except Exception:
                logger.exception("Failed to recalculate sentiment scores for item %d", item_id)


def backfill_graph(db: Session) -> dict:
    """Full idempotent backfill of all saved bookmarks into MongoDB graph."""
    articles_col = get_articles_collection()
    keywords_col = get_keywords_collection()
    log_col = get_graph_sync_log_collection()

    if articles_col is None or keywords_col is None:
        logger.warning("MongoDB not configured — skipping backfill")
        return {"items_processed": 0, "status": "skipped"}

    # Drop and rebuild keywords collection to ensure idempotency
    if keywords_col is not None:
        keywords_col.drop()
    keywords_col = get_keywords_collection()
    if keywords_col is not None:
        keywords_col.create_index("keyword", unique=True)

    started_at = datetime.now(UTC)
    if log_col is not None:
        log_col.insert_one({"event": "backfill_started", "started_at": started_at})

    # Query all saved item IDs
    saved_item_ids: list[int] = list(
        db.execute(
            select(Feedback.item_id)
            .where(Feedback.action == FeedbackAction.SAVED)
            .distinct()
        ).scalars().all()
    )

    batch_size = settings.graph_backfill_batch_size
    items_processed = 0

    for batch_start in range(0, len(saved_item_ids), batch_size):
        batch_ids = saved_item_ids[batch_start : batch_start + batch_size]

        # Fetch items with sources
        items_map: dict[int, Item] = {
            row.id: row
            for row in db.execute(
                select(Item).where(Item.id.in_(batch_ids))
            ).scalars().all()
        }
        source_ids = {item.source_id for item in items_map.values()}
        sources_map: dict[int, Source] = {
            row.id: row
            for row in db.execute(
                select(Source).where(Source.id.in_(source_ids))
            ).scalars().all()
        }

        # Fetch keywords per item
        kw_rows = db.execute(
            select(ItemKeyword).where(ItemKeyword.item_id.in_(batch_ids))
        ).scalars().all()
        keywords_by_item: dict[int, list[str]] = {}
        for row in kw_rows:
            keywords_by_item.setdefault(row.item_id, []).append(row.keyword)

        # Build article docs
        now = datetime.now(UTC)
        article_docs: list[dict] = []
        embed_items: list[tuple[int, str]] = []  # (item_id, embed_text)

        for item_id in batch_ids:
            item = items_map.get(item_id)
            if item is None:
                continue
            source = sources_map.get(item.source_id)
            keywords = keywords_by_item.get(item_id, [])
            doc = _build_article_doc(item, source, keywords, saved_at=now)
            article_docs.append(doc)

            embed_text = build_embedding_text(item.title, item.summary)
            if embed_text is not None:
                embed_items.append((item_id, embed_text))

        # Batch generate embeddings
        if embed_items:
            texts = [t for _, t in embed_items]
            try:
                embeddings = generate_embeddings(texts)
                embed_map = {
                    f"item_{embed_items[i][0]}": embeddings[i]
                    for i in range(len(embeddings))
                }
                for doc in article_docs:
                    if doc["_id"] in embed_map:
                        doc["embedding"] = embed_map[doc["_id"]]
            except Exception:
                logger.exception("Failed to generate batch embeddings for backfill")

        # Bulk upsert articles
        for doc in article_docs:
            try:
                _upsert_article(articles_col, doc)
            except Exception:
                logger.exception("Failed to upsert article %s during backfill", doc["_id"])

        # Aggregate keywords and co-occurrences per batch
        kw_freq: dict[str, int] = {}
        cooc_pairs: list[tuple[str, str]] = []

        for item_id in batch_ids:
            keywords = keywords_by_item.get(item_id, [])
            for kw in keywords:
                kw_freq[kw] = kw_freq.get(kw, 0) + 1
            cooc_pairs.extend(combinations(keywords, 2))

        for kw, freq in kw_freq.items():
            try:
                keywords_col.update_one(
                    {"keyword": kw},
                    {
                        "$inc": {"doc_frequency": freq, "bookmark_frequency": freq},
                        "$set": {"last_seen_at": now},
                        "$setOnInsert": {
                            "keyword": kw,
                            "sentiment_score": None,
                            "cooccurrences": [],
                        },
                    },
                    upsert=True,
                )
            except Exception:
                logger.exception("Failed to upsert keyword '%s' during backfill", kw)

        for kw_a, kw_b in cooc_pairs:
            try:
                _update_cooccurrence(keywords_col, kw_a, kw_b)
                _update_cooccurrence(keywords_col, kw_b, kw_a)
            except Exception:
                logger.exception("Failed to update co-occurrence (%s, %s) during backfill", kw_a, kw_b)

        items_processed += len(article_docs)

    completed_at = datetime.now(UTC)
    if log_col is not None:
        log_col.insert_one({
            "event": "backfill_completed",
            "started_at": started_at,
            "completed_at": completed_at,
            "items_processed": items_processed,
        })

    return {"items_processed": items_processed, "status": "completed"}


def get_keyword_graph(keyword: str, depth: int = 1) -> dict:
    """Return the keyword neighborhood graph up to `depth` hops."""
    keywords_col = get_keywords_collection()
    if keywords_col is None:
        return {}

    def _fetch_node(kw: str) -> dict | None:
        return keywords_col.find_one({"keyword": kw})

    root = _fetch_node(keyword)
    if root is None:
        return {}

    visited: set[str] = {keyword}
    neighbors: list[dict] = []

    # BFS up to `depth`
    current_level: list[str] = [keyword]
    for _ in range(depth):
        next_level: list[str] = []
        for kw in current_level:
            node = _fetch_node(kw)
            if node is None:
                continue
            for cooc in node.get("cooccurrences", []):
                neighbor_kw = cooc.get("keyword")
                count = cooc.get("count", 0)
                if neighbor_kw is None:
                    continue
                neighbor_doc = _fetch_node(neighbor_kw)
                entry = {
                    "keyword": neighbor_kw,
                    "count": count,
                    "doc_frequency": neighbor_doc.get("doc_frequency", 0) if neighbor_doc else 0,
                }
                neighbors.append(entry)
                if neighbor_kw not in visited:
                    visited.add(neighbor_kw)
                    next_level.append(neighbor_kw)
        current_level = next_level

    return {
        "keyword": keyword,
        "doc_frequency": root.get("doc_frequency", 0),
        "bookmark_frequency": root.get("bookmark_frequency", 0),
        "sentiment_score": root.get("sentiment_score") or 0.0,
        "neighbors": neighbors,
    }


def get_related_keywords(keyword: str, limit: int = 10) -> list[dict]:
    """Return the top co-occurring keywords, sorted by count desc."""
    keywords_col = get_keywords_collection()
    if keywords_col is None:
        return []

    doc = keywords_col.find_one({"keyword": keyword})
    if doc is None:
        return []

    cooccurrences = doc.get("cooccurrences", [])
    sorted_cooc = sorted(cooccurrences, key=lambda x: x.get("count", 0), reverse=True)
    return sorted_cooc[:limit]


def get_bookmark_keyword_cloud(limit: int = 30) -> list[dict]:
    """Return top keywords by bookmark frequency."""
    keywords_col = get_keywords_collection()
    if keywords_col is None:
        return []

    cursor = keywords_col.find(
        {},
        {"keyword": 1, "bookmark_frequency": 1, "sentiment_score": 1, "_id": 0},
    ).sort("bookmark_frequency", -1).limit(limit)

    return [
        {
            "keyword": doc["keyword"],
            "frequency": doc.get("bookmark_frequency", 0),
            "sentiment_score": doc.get("sentiment_score") or 0.0,
        }
        for doc in cursor
    ]
