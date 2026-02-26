# API Map

현재 `app/routers` 기준 엔드포인트 맵입니다.

## Health

- `GET /health`

## Auth

- `GET /auth/google/login`
- `GET /auth/google/callback`
- `GET /auth/me`
- `POST /auth/logout`

## Feed / Feedback / Event

- `GET /feeds/today`
- `POST /feedback`
- `POST /events/click`

## Bookmarks

- `GET /bookmarks`
- `POST /bookmarks/ask`
- `GET /bookmarks/explore`
- `GET /bookmarks/keywords`
- `GET /bookmarks/graph`
- `GET /bookmarks/graph/similarity`
- `GET /bookmarks/timeline`

## Insights (Public)

- `GET /insights/posts`
- `GET /insights/posts/{slug}`

## Admin

- `GET /admin/metrics`
- `GET /admin/keyword-sentiments`
- `GET /admin/user-stats`
- `POST /admin/backfill-keywords`
- `POST /admin/backfill-graph`
- `POST /admin/backfill-rss-published-at`
- `GET /admin/insights/posts`
- `POST /admin/insights/draft`
- `PATCH /admin/insights/posts/{post_id}`
- `POST /admin/insights/posts/{post_id}/publish`
- `POST /admin/insights/posts/{post_id}/unpublish`
- `DELETE /admin/insights/posts/{post_id}`
- `POST /admin/keywords/backfill-embeddings`

## Main-level Admin Endpoints

- `POST /admin/run-ingestion`
- `POST /admin/generate-feed/{slot}`
