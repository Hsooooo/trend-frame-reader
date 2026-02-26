# Data Model

## PostgreSQL ER Diagram

```mermaid
erDiagram
    USERS ||--o{ FEEDBACK : writes
    USERS ||--o{ ITEM_EVENTS : generates

    SOURCES ||--o{ ITEMS : publishes
    ITEMS ||--o{ ITEM_KEYWORDS : has

    FEEDS ||--o{ FEED_ITEMS : contains
    ITEMS ||--o{ FEED_ITEMS : included

    ITEMS ||--o{ FEEDBACK : receives
    ITEMS ||--o{ ITEM_EVENTS : receives

    INSIGHT_POSTS {
        int id PK
        string slug UK
        string title
        string status
        date period_start
        date period_end
        datetime created_at
        datetime published_at
    }

    USERS {
        int id PK
        string google_id UK
        string email UK
        string name
        bool is_owner
        datetime created_at
    }

    SOURCES {
        int id PK
        string type
        string name
        string category
        bool enabled
        float weight
        datetime last_fetched_at
    }

    ITEMS {
        int id PK
        int source_id FK
        string canonical_url UK
        string title
        string translated_title_ko
        datetime published_at
        datetime fetched_at
        string language
        float score
    }

    ITEM_KEYWORDS {
        int id PK
        int item_id FK
        string keyword
        float relevance_score
        datetime created_at
    }

    FEEDS {
        int id PK
        date feed_date
        string slot
        datetime generated_at
    }

    FEED_ITEMS {
        int id PK
        int feed_id FK
        int item_id FK
        int rank
        string short_reason
    }

    FEEDBACK {
        int id PK
        int item_id FK
        string action
        string slot
        int rank
        int source_id
        string category
        int feed_id
        int user_id
        datetime created_at
    }

    ITEM_EVENTS {
        int id PK
        int item_id FK
        string event_type
        string slot
        int rank
        int source_id
        string category
        int feed_id
        int user_id
        datetime created_at
    }
```

## 핵심 제약

- `feeds`: `(feed_date, slot)` unique
- `feed_items`: `(feed_id, item_id)` unique
- `items.canonical_url` unique
- `users.google_id`, `users.email`, `insight_posts.slug` unique

## MongoDB Collections

- `articles`
  - 주로 북마크 기반 문서 저장(`item_id`, `title`, `summary`, `keywords`, `embedding`, `user_id`)
  - RAG/타임라인/그래프 아티클 노드 조회에 사용
- `keywords`
  - 키워드 집계(`doc_frequency`, `bookmark_frequency`, `cooccurrences`, `sentiment_score`, `embedding`)
  - 그래프 탐색/유사도 탐색에 사용
- `graph_sync_log`
  - 그래프 백필 시작/완료 이벤트 기록

## 이벤트 모델링 원칙

- `feedback`는 append-only 이벤트 저장
- `item_events`도 append-only(`impression`, `click`)
- 현재 상태는 "최신 row"를 집계해 계산
