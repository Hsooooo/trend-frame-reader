from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import (
    Feedback,
    FeedbackAction,
    InsightPost,
    Item,
    ItemEvent,
    ItemEventType,
    ItemKeyword,
    Source,
)
from app.mongo import get_keywords_collection
from app.services.keyword_embeddings import get_topic_clusters

logger = logging.getLogger(__name__)

MIN_BODY_LEN = 200
TOP_K_KEYWORDS = 30
TOP_CTR_ITEMS = 5
MIN_IMPRESSIONS_FOR_CTR = 3


def _make_slug(db: Session, period_end: date) -> str:
    base = f"{period_end.isoformat()}-weekly-trend"
    slug = base
    suffix = 1
    while db.execute(
        select(InsightPost).where(InsightPost.slug == slug)
    ).scalar_one_or_none() is not None:
        suffix += 1
        slug = f"{base}-{suffix}"
    return slug


def _get_period_keywords(
    db: Session, start_dt: datetime, end_dt: datetime, top_k: int = TOP_K_KEYWORDS
) -> list[dict]:
    """Get top keywords by doc_frequency (number of articles) in the period."""
    stmt = (
        select(
            ItemKeyword.keyword,
            func.count(func.distinct(ItemKeyword.item_id)).label("doc_frequency"),
        )
        .join(Item, Item.id == ItemKeyword.item_id)
        .where(
            Item.published_at >= start_dt,
            Item.published_at < end_dt,
        )
        .group_by(ItemKeyword.keyword)
        .order_by(func.count(func.distinct(ItemKeyword.item_id)).desc())
        .limit(top_k)
    )
    rows = db.execute(stmt).all()

    # Determine language from MongoDB keywords collection
    keywords_col = get_keywords_collection()
    result = []
    for row in rows:
        language = "en"
        if keywords_col is not None:
            kw_doc = keywords_col.find_one(
                {"keyword": row.keyword}, {"language": 1}
            )
            if kw_doc and kw_doc.get("language"):
                language = kw_doc["language"]
            else:
                # Heuristic: if contains Korean characters, mark as ko
                if any("\uac00" <= ch <= "\ud7a3" for ch in row.keyword):
                    language = "ko"
        result.append({
            "keyword": row.keyword,
            "doc_frequency": row.doc_frequency,
            "language": language,
        })
    return result


def _get_cluster_articles(
    db: Session, cluster: dict, start_dt: datetime, end_dt: datetime
) -> dict:
    """Get articles for a cluster, split by language."""
    keywords = []
    if cluster.get("en_keyword"):
        keywords.append(cluster["en_keyword"])
    if cluster.get("ko_keyword"):
        keywords.append(cluster["ko_keyword"])
    if not keywords:
        return {"en_articles": [], "ko_articles": []}

    stmt = (
        select(Item, Source.name.label("source_name"))
        .join(ItemKeyword, ItemKeyword.item_id == Item.id)
        .join(Source, Source.id == Item.source_id)
        .where(
            ItemKeyword.keyword.in_(keywords),
            Item.published_at >= start_dt,
            Item.published_at < end_dt,
        )
        .distinct()
        .limit(10)
    )
    rows = db.execute(stmt).all()

    en_articles = []
    ko_articles = []
    for item, source_name in rows:
        # Get sentiment from feedback
        liked = db.execute(
            select(func.count()).select_from(Feedback).where(
                Feedback.item_id == item.id,
                Feedback.action == FeedbackAction.LIKED,
            )
        ).scalar_one()
        disliked = db.execute(
            select(func.count()).select_from(Feedback).where(
                Feedback.item_id == item.id,
                Feedback.action == FeedbackAction.DISLIKED,
            )
        ).scalar_one()

        if liked > disliked:
            sentiment_label = "👍"
        elif disliked > liked:
            sentiment_label = "👎"
        else:
            sentiment_label = ""

        article = {
            "title": item.translated_title_ko or item.title,
            "url": item.url,
            "source": source_name,
            "sentiment_label": sentiment_label,
        }

        if item.language == "ko":
            ko_articles.append(article)
        else:
            en_articles.append(article)

    return {"en_articles": en_articles, "ko_articles": ko_articles}


def _get_temperature_label(
    en_count: int, ko_count: int, en_sentiment: str, ko_sentiment: str
) -> str:
    """Generate a deterministic temperature difference label."""
    if en_count == 0 and ko_count == 0:
        return "데이터 부족"
    if en_count == 0:
        return "국내에서만 주목"
    if ko_count == 0:
        return "해외에서만 주목"
    ratio = max(en_count, ko_count) / max(min(en_count, ko_count), 1)
    if ratio > 3:
        dominant = "해외" if en_count > ko_count else "국내"
        return f"{dominant}에서 관심 집중 (비율 {ratio:.1f}x)"
    return "국내외 균형 있는 관심"


def _get_ctr_top_items(
    db: Session, start_dt: datetime, end_dt: datetime, top_k: int = TOP_CTR_ITEMS
) -> list[dict]:
    """Get top items by CTR (click/impression ratio)."""
    imp_count = func.count(case((ItemEvent.event_type == ItemEventType.IMPRESSION.value, 1)))
    clk_count = func.count(case((ItemEvent.event_type == ItemEventType.CLICK.value, 1)))

    stmt = (
        select(
            ItemEvent.item_id,
            imp_count.label("impressions"),
            clk_count.label("clicks"),
        )
        .where(
            ItemEvent.created_at >= start_dt,
            ItemEvent.created_at < end_dt,
        )
        .group_by(ItemEvent.item_id)
        .having(imp_count >= MIN_IMPRESSIONS_FOR_CTR)
    )
    rows = db.execute(stmt).all()

    items_with_ctr = []
    for row in rows:
        ctr = row.clicks / row.impressions if row.impressions > 0 else 0.0
        items_with_ctr.append({
            "item_id": row.item_id,
            "impressions": row.impressions,
            "clicks": row.clicks,
            "ctr": ctr,
        })

    items_with_ctr.sort(key=lambda x: x["ctr"], reverse=True)
    top_items = items_with_ctr[:top_k]

    # Fetch item details
    result = []
    for entry in top_items:
        item = db.get(Item, entry["item_id"])
        if item is None:
            continue
        source = db.get(Source, item.source_id)
        category = source.category if source else "unknown"
        result.append({
            "title": item.translated_title_ko or item.title,
            "url": item.url,
            "ctr": entry["ctr"],
            "impressions": entry["impressions"],
            "clicks": entry["clicks"],
            "category": category,
        })

    return result


def _get_category_save_rates(
    db: Session, start_dt: datetime, end_dt: datetime
) -> list[dict]:
    """Get save vs skip ratio per category."""
    saved_count = func.count(case((Feedback.action == FeedbackAction.SAVED, 1)))
    skipped_count = func.count(case((Feedback.action == FeedbackAction.SKIPPED, 1)))

    stmt = (
        select(
            Source.category,
            saved_count.label("saved"),
            skipped_count.label("skipped"),
        )
        .join(Item, Item.id == Feedback.item_id)
        .join(Source, Source.id == Item.source_id)
        .where(
            Feedback.action.in_([FeedbackAction.SAVED, FeedbackAction.SKIPPED]),
            Feedback.created_at >= start_dt,
            Feedback.created_at < end_dt,
        )
        .group_by(Source.category)
        .order_by(Source.category)
    )
    rows = db.execute(stmt).all()

    result = []
    for row in rows:
        total = row.saved + row.skipped
        save_rate = row.saved / total if total > 0 else 0.0
        result.append({
            "category": row.category,
            "saved": row.saved,
            "skipped": row.skipped,
            "save_rate": save_rate,
        })

    result.sort(key=lambda x: x["save_rate"], reverse=True)
    return result


def _render_body(
    period_start: date,
    period_end: date,
    clusters: list[dict],
    cluster_articles: dict[int, dict],
    ctr_items: list[dict],
    category_rates: list[dict],
    total_items: int,
    en_items: int,
    ko_items: int,
    matched_topics: int,
) -> str:
    """Render the insight post body as markdown."""
    lines = []
    lines.append(f"## {period_start} ~ {period_end} IT 트렌드 요약\n")
    lines.append("이번 주 Trend Frame에 수집된 기사와 사용자 반응을 분석했습니다.\n")
    lines.append("### 주요 토픽 (국내외 비교)\n")

    top_clusters = clusters[:10]
    for rank, cluster in enumerate(top_clusters, 1):
        articles = cluster_articles.get(rank - 1, {"en_articles": [], "ko_articles": []})
        en_articles = articles.get("en_articles", [])
        ko_articles = articles.get("ko_articles", [])

        lines.append(f"#### {rank}. {cluster['topic']}\n")

        if en_articles:
            lines.append(f"**해외 기사** ({len(en_articles)}건)")
            for a in en_articles[:5]:
                sentiment = f" {a['sentiment_label']}" if a.get("sentiment_label") else ""
                lines.append(f"- [{a['title']}]({a['url']}) — {a['source']}{sentiment}")
            lines.append("")

        if ko_articles:
            lines.append(f"**국내 기사** ({len(ko_articles)}건)")
            for a in ko_articles[:5]:
                sentiment = f" {a['sentiment_label']}" if a.get("sentiment_label") else ""
                lines.append(f"- [{a['title']}]({a['url']}) — {a['source']}{sentiment}")
            lines.append("")

        if not en_articles and not ko_articles:
            lines.append("_관련 기사 데이터 부족_\n")

        en_sentiment = "neutral"
        ko_sentiment = "neutral"
        temp_label = _get_temperature_label(
            len(en_articles), len(ko_articles), en_sentiment, ko_sentiment
        )
        lines.append(f"> 국내외 온도차: {temp_label}\n")

    # CTR TOP 5
    lines.append("### 가장 눈길을 끈 기사 TOP 5\n")
    if ctr_items:
        lines.append("| 순위 | 제목 | 클릭률 | 카테고리 |")
        lines.append("|------|------|--------|----------|")
        for i, item in enumerate(ctr_items, 1):
            ctr_pct = f"{item['ctr'] * 100:.1f}%"
            lines.append(
                f"| {i} | [{item['title']}]({item['url']}) | {ctr_pct} | {item['category']} |"
            )
    else:
        lines.append("_CTR 데이터 부족 (최소 3회 이상 노출된 기사가 필요합니다)_")
    lines.append("")

    # Category save rates
    lines.append("### 카테고리별 저장률\n")
    if category_rates:
        lines.append("| 카테고리 | 저장 | 스킵 | 저장률 |")
        lines.append("|----------|------|------|--------|")
        for r in category_rates:
            rate_pct = f"{r['save_rate'] * 100:.1f}%"
            lines.append(
                f"| {r['category']} | {r['saved']} | {r['skipped']} | {rate_pct} |"
            )
    else:
        lines.append("_저장/스킵 데이터 부족_")
    lines.append("")

    # Data basis
    lines.append("### 데이터 기준\n")
    lines.append(f"- 분석 기간: {period_start} ~ {period_end}")
    lines.append(f"- 집계 기사 수: {total_items}건 (해외 {en_items}건 / 국내 {ko_items}건)")
    lines.append(f"- 크로스랭귀지 매칭 토픽: {matched_topics}건")

    return "\n".join(lines)


def generate_draft(db: Session, days: int = 7) -> InsightPost:
    """Generate a weekly insight draft post."""
    now = datetime.now(UTC)
    period_end = now.date()
    period_start = period_end - timedelta(days=days)
    start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    # Count total items in period
    total_items = db.execute(
        select(func.count()).select_from(Item).where(
            Item.published_at >= start_dt,
            Item.published_at < end_dt,
        )
    ).scalar_one()
    en_items = db.execute(
        select(func.count()).select_from(Item).where(
            Item.published_at >= start_dt,
            Item.published_at < end_dt,
            Item.language == "en",
        )
    ).scalar_one()
    ko_items = db.execute(
        select(func.count()).select_from(Item).where(
            Item.published_at >= start_dt,
            Item.published_at < end_dt,
            Item.language == "ko",
        )
    ).scalar_one()

    # Get top keywords by doc_frequency
    period_keywords = _get_period_keywords(db, start_dt, end_dt)

    # Build cross-language clusters
    keywords_col = get_keywords_collection()
    if keywords_col is not None and period_keywords:
        clusters = get_topic_clusters(keywords_col, period_keywords)
    else:
        # Fallback: plain keyword frequency table
        clusters = [
            {
                "topic": kw["keyword"],
                "en_keyword": kw["keyword"] if kw["language"] == "en" else None,
                "ko_keyword": kw["keyword"] if kw["language"] == "ko" else None,
                "total_frequency": kw["doc_frequency"],
                "en_frequency": kw["doc_frequency"] if kw["language"] == "en" else 0,
                "ko_frequency": kw["doc_frequency"] if kw["language"] == "ko" else 0,
                "similarity": None,
            }
            for kw in period_keywords
        ]

    # Get articles for each cluster
    cluster_articles = {}
    for i, cluster in enumerate(clusters[:10]):
        cluster_articles[i] = _get_cluster_articles(db, cluster, start_dt, end_dt)

    # Count matched topics
    matched_topics = sum(
        1 for c in clusters if c.get("en_keyword") and c.get("ko_keyword")
    )

    # CTR top items
    ctr_items = _get_ctr_top_items(db, start_dt, end_dt)

    # Category save rates
    category_rates = _get_category_save_rates(db, start_dt, end_dt)

    # Render body
    body = _render_body(
        period_start, period_end, clusters, cluster_articles,
        ctr_items, category_rates, total_items, en_items, ko_items, matched_topics,
    )

    # Build title and summary
    title = f"{period_start} ~ {period_end} 주간 IT 트렌드 인사이트"
    top_topics = [c["topic"] for c in clusters[:3]]
    summary = f"이번 주 주요 토픽: {', '.join(top_topics)}" if top_topics else "이번 주 트렌드 요약"

    # Create InsightPost
    slug = _make_slug(db, period_end)
    post = InsightPost(
        slug=slug,
        title=title,
        summary=summary,
        body=body,
        status="draft",
        period_start=period_start,
        period_end=period_end,
    )
    db.add(post)
    db.commit()
    db.refresh(post)

    return post


def publish_post(db: Session, post_id: int) -> InsightPost:
    """Publish a draft insight post."""
    post = db.get(InsightPost, post_id)
    if post is None:
        raise ValueError("post_not_found")
    if not post.body or len(post.body) < MIN_BODY_LEN:
        raise ValueError("body_too_short")
    if not post.title:
        raise ValueError("title_required")
    if not post.summary:
        raise ValueError("summary_required")

    post.status = "published"
    post.published_at = datetime.now(UTC)
    db.commit()
    db.refresh(post)
    return post


def unpublish_post(db: Session, post_id: int) -> InsightPost:
    """Unpublish a published insight post."""
    post = db.get(InsightPost, post_id)
    if post is None:
        raise ValueError("post_not_found")

    post.status = "draft"
    post.published_at = None
    db.commit()
    db.refresh(post)
    return post
