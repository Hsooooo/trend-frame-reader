from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Source, SourceType

DEFAULT_SOURCES: list[dict] = [
    {"type": SourceType.HN, "name": "Hacker News", "url": "https://news.ycombinator.com/", "category": "tech", "weight": 1.1},
    {"type": SourceType.RSS, "name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "category": "tech", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC Top Stories", "url": "https://feeds.bbci.co.uk/news/rss.xml", "category": "world", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "category": "world", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "category": "business", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC Technology", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "category": "tech", "weight": 1.1},
    {
        "type": SourceType.RSS,
        "name": "BBC Science & Environment",
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "category": "science",
        "weight": 1.0,
    },
    {"type": SourceType.RSS, "name": "DW All (EN)", "url": "https://rss.dw.com/rdf/rss-en-all", "category": "world", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world", "category": "world", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW Business", "url": "https://rss.dw.com/rdf/rss-en-bus", "category": "business", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW Science", "url": "https://rss.dw.com/xml/rss_en_science", "category": "science", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW Environment", "url": "https://rss.dw.com/xml/rss_en_environment", "category": "science", "weight": 1.0},
    {
        "type": SourceType.RSS,
        "name": "Cloudflare Changelog (All)",
        "url": "https://developers.cloudflare.com/changelog/rss/index.xml",
        "category": "tech",
        "weight": 1.1,
    },
    {
        "type": SourceType.RSS,
        "name": "Cloudflare Changelog (Developer Platform)",
        "url": "https://developers.cloudflare.com/changelog/rss/developer-platform.xml",
        "category": "tech",
        "weight": 1.1,
    },
    {
        "type": SourceType.RSS,
        "name": "Cloudflare Changelog (Application Performance)",
        "url": "https://developers.cloudflare.com/changelog/rss/application-performance.xml",
        "category": "tech",
        "weight": 1.0,
    },
    {"type": SourceType.RSS, "name": "MK 전체뉴스", "url": "https://www.mk.co.kr/rss/40300001/", "category": "korea", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 경제", "url": "https://www.mk.co.kr/rss/30100041/", "category": "korea-business", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 증권", "url": "https://www.mk.co.kr/rss/50200011/", "category": "korea-business", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 국제", "url": "https://www.mk.co.kr/rss/30300018/", "category": "korea", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 전체기사", "url": "https://www.mbn.co.kr/rss/", "category": "korea", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 정치", "url": "https://www.mbn.co.kr/rss/politics/", "category": "korea", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 경제", "url": "https://www.mbn.co.kr/rss/economy/", "category": "korea-business", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 사회", "url": "https://www.mbn.co.kr/rss/society/", "category": "korea", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 국제", "url": "https://www.mbn.co.kr/rss/international/", "category": "korea", "weight": 1.0},
]


def apply_schema_upgrades(session: Session) -> None:
    # Lightweight migration path without Alembic.
    session.execute(
        text("ALTER TABLE sources ADD COLUMN IF NOT EXISTS category VARCHAR(64) NOT NULL DEFAULT 'general'")
    )
    session.commit()


def sync_seed_sources(session: Session) -> dict:
    existing = {x.url: x for x in session.execute(select(Source)).scalars().all()}
    created = 0
    updated = 0

    for row in DEFAULT_SOURCES:
        source = existing.get(row["url"])
        if source:
            changed = False
            for key in ("type", "name", "category", "weight"):
                if getattr(source, key) != row[key]:
                    setattr(source, key, row[key])
                    changed = True
            desired_enabled = row.get("enabled", True)
            if source.enabled != desired_enabled:
                source.enabled = desired_enabled
                changed = True
            if changed:
                updated += 1
            continue

        session.add(
            Source(
                type=row["type"],
                name=row["name"],
                url=row["url"],
                category=row["category"],
                weight=row["weight"],
                enabled=row["enabled"] if "enabled" in row else True,
            )
        )
        created += 1

    session.commit()
    return {"created": created, "updated": updated, "total": len(DEFAULT_SOURCES)}
