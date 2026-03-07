from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Feedback, FeedbackAction, Item, ItemKeyword, Source
from app.mongo import get_market_articles_collection
from app.services.market_entities import extract_market_entities

logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "unknown"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def build_market_article_doc(item: Item, source: Source | None, keywords: list[str]) -> dict:
    entities = extract_market_entities(item.title, item.summary)
    return {
        "_id": f"item_{item.id}",
        "item_id": item.id,
        "url": item.url,
        "title": item.title,
        "source": source.name if source else None,
        "category": source.category if source else None,
        "published_at": item.published_at,
        "fetched_at": item.fetched_at,
        "summary": item.summary,
        "language": item.language,
        "keywords": keywords,
        **entities,
    }


def sync_market_article(item: Item, source: Source | None, keywords: list[str]) -> bool:
    collection = get_market_articles_collection()
    if collection is None:
        return False
    doc = build_market_article_doc(item, source, keywords)
    collection.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    return True


def backfill_market_graph(db: Session, limit: int | None = None) -> dict:
    collection = get_market_articles_collection()
    if collection is None:
        return {"processed": 0, "synced": 0, "failed": 0, "status": "skipped"}

    stmt = select(Item).order_by(Item.id)
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)
    items = db.execute(stmt).scalars().all()
    if not items:
        return {"processed": 0, "synced": 0, "failed": 0, "status": "completed"}

    source_ids = {item.source_id for item in items}
    sources = db.execute(select(Source).where(Source.id.in_(source_ids))).scalars().all()
    sources_map = {source.id: source for source in sources}

    kw_rows = db.execute(
        select(ItemKeyword.item_id, ItemKeyword.keyword).where(
            ItemKeyword.item_id.in_([item.id for item in items])
        )
    ).all()
    keywords_by_item: dict[int, list[str]] = {}
    for item_id, keyword in kw_rows:
        keywords_by_item.setdefault(item_id, []).append(keyword)

    synced = 0
    failed = 0
    for item in items:
        try:
            ok = sync_market_article(item, sources_map.get(item.source_id), keywords_by_item.get(item.id, []))
            if ok:
                synced += 1
        except Exception:
            failed += 1
            logger.exception("Failed to sync market article item_id=%s", item.id)

    return {
        "processed": len(items),
        "synced": synced,
        "failed": failed,
        "status": "completed" if failed == 0 else "completed_with_errors",
    }


def _current_saved_item_ids(db: Session, user_id: int) -> set[int]:
    latest_feedback = (
        select(Feedback.item_id, func.max(Feedback.id).label("max_id"))
        .where(
            Feedback.action.in_([FeedbackAction.SAVED.value, FeedbackAction.SKIPPED.value]),
            Feedback.user_id == user_id,
        )
        .group_by(Feedback.item_id)
        .subquery()
    )
    rows = db.execute(
        select(Feedback.item_id)
        .join(latest_feedback, Feedback.id == latest_feedback.c.max_id)
        .where(Feedback.action == FeedbackAction.SAVED.value)
    ).scalars().all()
    return set(rows)


def get_ticker_market_graph(
    db: Session,
    ticker: str,
    days: int = 30,
    max_articles: int = 20,
    bookmarks_only: bool = True,
    user_id: int | None = None,
) -> dict:
    collection = get_market_articles_collection()
    if collection is None:
        return {}

    symbol = ticker.upper().strip()
    query: dict = {"tickers.symbol": symbol}
    if days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        query["$or"] = [
            {"published_at": {"$gte": cutoff}},
            {"published_at": None, "fetched_at": {"$gte": cutoff}},
        ]

    cursor = collection.find(
        query,
        {
            "item_id": 1,
            "title": 1,
            "url": 1,
            "source": 1,
            "published_at": 1,
            "companies": 1,
            "tickers": 1,
            "events": 1,
            "themes": 1,
        },
    ).limit(max_articles * 8)
    docs = list(cursor)

    if bookmarks_only and user_id is not None:
        saved_ids = _current_saved_item_ids(db, user_id)
        docs = [doc for doc in docs if doc.get("item_id") in saved_ids]

    docs = docs[:max_articles]
    if not docs:
        return {}

    ticker_counts: Counter[str] = Counter()
    ticker_meta: dict[str, dict] = {}
    company_counts: Counter[str] = Counter()
    event_counts: Counter[str] = Counter()
    event_meta: dict[str, dict] = {}
    theme_counts: Counter[str] = Counter()

    article_nodes: list[dict] = []
    edges: list[dict] = []
    company_ticker_edges: set[tuple[str, str]] = set()

    for doc in docs:
        item_id = doc.get("item_id")
        if item_id is None:
            continue

        article_id = f"item_{item_id}"
        article_tickers = []
        article_companies = []
        article_events = []
        article_themes = []

        for ticker_row in doc.get("tickers", []):
            raw_symbol = str(ticker_row.get("symbol", "")).upper().strip()
            if not raw_symbol:
                continue
            ticker_counts[raw_symbol] += 1
            ticker_meta.setdefault(
                raw_symbol,
                {
                    "id": f"ticker_{_slugify(raw_symbol)}",
                    "symbol": raw_symbol,
                    "exchange": ticker_row.get("exchange"),
                    "is_focus": raw_symbol == symbol,
                },
            )
            edges.append(
                {
                    "source": article_id,
                    "target": ticker_meta[raw_symbol]["id"],
                    "type": "mentions_ticker",
                    "weight": 1,
                }
            )
            article_tickers.append(raw_symbol)

        for company_row in doc.get("companies", []):
            company_name = str(company_row.get("canonical_name") or company_row.get("raw_name") or "").strip()
            if not company_name:
                continue
            company_counts[company_name] += 1
            company_id = f"company_{_slugify(company_name)}"
            article_companies.append(company_name)
            edges.append(
                {
                    "source": article_id,
                    "target": company_id,
                    "type": "mentions_company",
                    "weight": 1,
                }
            )

        for event_row in doc.get("events", []):
            event_type = str(event_row.get("type", "")).strip()
            label = str(event_row.get("label", event_type)).strip() or event_type
            if not event_type:
                continue
            event_counts[event_type] += 1
            event_meta.setdefault(
                event_type,
                {
                    "id": f"event_{_slugify(event_type)}",
                    "event_type": event_type,
                    "label": label,
                },
            )
            article_events.append(label)
            edges.append(
                {
                    "source": article_id,
                    "target": event_meta[event_type]["id"],
                    "type": "has_event",
                    "weight": 1,
                }
            )

        for theme_row in doc.get("themes", []):
            theme_name = str(theme_row.get("name", "")).strip()
            if not theme_name:
                continue
            theme_counts[theme_name] += 1
            article_themes.append(theme_name)
            edges.append(
                {
                    "source": article_id,
                    "target": f"theme_{_slugify(theme_name)}",
                    "type": "has_theme",
                    "weight": 1,
                }
            )

        article_nodes.append(
            {
                "id": article_id,
                "item_id": item_id,
                "title": doc.get("title", ""),
                "url": doc.get("url", ""),
                "source": doc.get("source"),
                "published_at": _iso(doc.get("published_at")),
                "companies": article_companies,
                "tickers": article_tickers,
                "events": article_events,
                "themes": article_themes,
            }
        )

        for company_row in doc.get("companies", []):
            company_name = str(company_row.get("canonical_name") or company_row.get("raw_name") or "").strip()
            if not company_name:
                continue
            company_id = f"company_{_slugify(company_name)}"
            for ticker_row in doc.get("tickers", []):
                raw_symbol = str(ticker_row.get("symbol", "")).upper().strip()
                linked_company = str(ticker_row.get("company_name", "")).strip()
                if not raw_symbol:
                    continue
                if linked_company and linked_company != company_name:
                    continue
                target_id = f"ticker_{_slugify(raw_symbol)}"
                pair = (company_id, target_id)
                if pair in company_ticker_edges:
                    continue
                company_ticker_edges.add(pair)
                edges.append(
                    {
                        "source": company_id,
                        "target": target_id,
                        "type": "company_has_ticker",
                        "weight": 1,
                    }
                )

    ticker_nodes = [
        {
            **meta,
            "mention_count": ticker_counts[symbol_key],
        }
        for symbol_key, meta in ticker_meta.items()
    ]
    ticker_nodes.sort(key=lambda node: (not node["is_focus"], -node["mention_count"], node["symbol"]))

    company_nodes = [
        {
            "id": f"company_{_slugify(name)}",
            "canonical_name": name,
            "mention_count": count,
        }
        for name, count in company_counts.items()
    ]
    company_nodes.sort(key=lambda node: (-node["mention_count"], node["canonical_name"]))

    event_nodes = [
        {
            **event_meta[event_type],
            "count": count,
        }
        for event_type, count in event_counts.items()
    ]
    event_nodes.sort(key=lambda node: (-node["count"], node["event_type"]))

    theme_nodes = [
        {
            "id": f"theme_{_slugify(name)}",
            "name": name,
            "count": count,
        }
        for name, count in theme_counts.items()
    ]
    theme_nodes.sort(key=lambda node: (-node["count"], node["name"]))

    return {
        "focus_ticker": symbol,
        "ticker_nodes": ticker_nodes,
        "company_nodes": company_nodes,
        "event_nodes": event_nodes,
        "theme_nodes": theme_nodes,
        "article_nodes": article_nodes,
        "edges": edges,
    }
