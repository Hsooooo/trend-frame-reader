from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Source, SourceType

DEFAULT_SOURCES: list[dict] = [
    {"type": SourceType.HN, "name": "Hacker News", "url": "https://news.ycombinator.com/", "category": "devtools", "weight": 1.1},
    {"type": SourceType.RSS, "name": "GeekNews", "url": "https://news.hada.io/rss/news", "category": "korea-tech", "weight": 1.1},
    {"type": SourceType.RSS, "name": "OpenAI Blog", "url": "https://openai.com/blog/rss.xml", "category": "ai", "weight": 1.1},
    {"type": SourceType.RSS, "name": "BBC Top Stories", "url": "https://feeds.bbci.co.uk/news/rss.xml", "category": "world-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC World", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "category": "world-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC Business", "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "category": "world-economy", "weight": 1.0},
    {"type": SourceType.RSS, "name": "BBC Technology", "url": "https://feeds.bbci.co.uk/news/technology/rss.xml", "category": "devtools", "weight": 1.1},
    {
        "type": SourceType.RSS,
        "name": "BBC Science & Environment",
        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        "category": "world-politics",
        "weight": 1.0,
    },
    {"type": SourceType.RSS, "name": "DW All (EN)", "url": "https://rss.dw.com/rdf/rss-en-all", "category": "world-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world", "category": "world-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW Business", "url": "https://rss.dw.com/rdf/rss-en-bus", "category": "world-economy", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW Science", "url": "https://rss.dw.com/xml/rss_en_science", "category": "ai", "weight": 1.0},
    {"type": SourceType.RSS, "name": "DW Environment", "url": "https://rss.dw.com/xml/rss_en_environment", "category": "world-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "GitHub Blog", "url": "https://github.blog/feed/", "category": "devtools", "weight": 1.1},
    {"type": SourceType.RSS, "name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "category": "ai", "weight": 1.1},
    {
        "type": SourceType.RSS,
        "name": "Cloudflare Changelog (All)",
        "url": "https://developers.cloudflare.com/changelog/rss/index.xml",
        "category": "infra-cloud",
        "weight": 1.1,
    },
    {
        "type": SourceType.RSS,
        "name": "Cloudflare Changelog (Developer Platform)",
        "url": "https://developers.cloudflare.com/changelog/rss/developer-platform.xml",
        "category": "infra-cloud",
        "weight": 1.1,
    },
    {
        "type": SourceType.RSS,
        "name": "Cloudflare Changelog (Application Performance)",
        "url": "https://developers.cloudflare.com/changelog/rss/application-performance.xml",
        "category": "infra-cloud",
        "weight": 1.0,
    },
    {"type": SourceType.RSS, "name": "Krebs on Security", "url": "https://krebsonsecurity.com/feed/", "category": "security", "weight": 1.0},
    {"type": SourceType.RSS, "name": "The Hacker News", "url": "https://feeds.feedburner.com/TheHackersNews", "category": "security", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 전체뉴스", "url": "https://www.mk.co.kr/rss/40300001/", "category": "korea-society", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 경제", "url": "https://www.mk.co.kr/rss/30100041/", "category": "korea-economy", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 증권", "url": "https://www.mk.co.kr/rss/50200011/", "category": "korea-markets", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MK 국제", "url": "https://www.mk.co.kr/rss/30300018/", "category": "world-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 전체기사", "url": "https://www.mbn.co.kr/rss/", "category": "korea-society", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 정치", "url": "https://www.mbn.co.kr/rss/politics/", "category": "korea-politics", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 경제", "url": "https://www.mbn.co.kr/rss/economy/", "category": "korea-economy", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 사회", "url": "https://www.mbn.co.kr/rss/society/", "category": "korea-society", "weight": 1.0},
    {"type": SourceType.RSS, "name": "MBN 국제", "url": "https://www.mbn.co.kr/rss/international/", "category": "world-politics", "weight": 1.0},
]


def apply_schema_upgrades(session: Session) -> None:
    # Lightweight migration path without Alembic.
    session.execute(
        text("ALTER TABLE sources ADD COLUMN IF NOT EXISTS category VARCHAR(64) NOT NULL DEFAULT 'general'")
    )
    session.execute(
        text("ALTER TABLE items ADD COLUMN IF NOT EXISTS translated_title_ko VARCHAR(512)")
    )
    session.execute(
        text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'feedback'
                      AND column_name = 'action'
                      AND data_type = 'USER-DEFINED'
                ) THEN
                    ALTER TABLE feedback
                    ALTER COLUMN action TYPE VARCHAR(32)
                    USING action::text;
                END IF;
            END $$;
            """
        )
    )
    session.execute(text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS slot VARCHAR(8)"))
    session.execute(text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS rank INTEGER"))
    session.execute(text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS source_id INTEGER"))
    session.execute(text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS category VARCHAR(64)"))
    session.execute(text("ALTER TABLE feedback ADD COLUMN IF NOT EXISTS feed_id INTEGER"))
    # Normalize historical enum-name rows (e.g. SAVED/SKIPPED) to lowercase values.
    session.execute(text("UPDATE feedback SET action = lower(action) WHERE action <> lower(action)"))
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS item_events (
                id SERIAL PRIMARY KEY,
                item_id INTEGER NOT NULL REFERENCES items(id),
                event_type VARCHAR(32) NOT NULL,
                slot VARCHAR(8),
                rank INTEGER,
                source_id INTEGER REFERENCES sources(id),
                category VARCHAR(64),
                feed_id INTEGER REFERENCES feeds(id),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_item_events_type_created_at ON item_events(event_type, created_at)"
        )
    )
    # Phase 2: summary field for keyword extraction
    session.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS summary TEXT"))
    # Phase 2: item_keywords table for keyword sentiment analysis
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS item_keywords (
                id SERIAL PRIMARY KEY,
                item_id INTEGER NOT NULL REFERENCES items(id),
                keyword VARCHAR(128) NOT NULL,
                relevance_score FLOAT NOT NULL DEFAULT 0.0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    session.execute(
        text("CREATE INDEX IF NOT EXISTS idx_item_keywords_keyword ON item_keywords(keyword)")
    )
    session.execute(
        text("CREATE INDEX IF NOT EXISTS idx_item_keywords_item_id ON item_keywords(item_id)")
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
