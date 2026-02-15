# trend-frame-reader

Phase 1 backend for Trend x Frame Reader.

## Stack
- FastAPI
- PostgreSQL
- SQLAlchemy
- APScheduler

## Run (Docker)
```bash
docker compose up --build
```

## Run (Local)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg2://app:app@localhost:5432/trend_frame'
uvicorn app.main:app --reload
```

## API
- `GET /health`
- `POST /admin/run-ingestion` (requires `Authorization: Bearer <ADMIN_TOKEN>`)
- `POST /admin/generate-feed/am|pm` (requires `Authorization: Bearer <ADMIN_TOKEN>`)
- `GET /admin/metrics?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD` (requires `Authorization: Bearer <ADMIN_TOKEN>`)
- `GET /admin/keyword-sentiments?date_from=YYYY-MM-DD&date_to=YYYY-MM-DD&min_feedback=2&limit=50` (requires `Authorization: Bearer <ADMIN_TOKEN>`)
- `POST /admin/backfill-keywords` (requires `Authorization: Bearer <ADMIN_TOKEN>`)
- `GET /feeds/today?slot=am|pm`
- `POST /feedback` with `{ "item_id": 1, "action": "saved|skipped|liked|disliked" }`
- `POST /events/click` with `{ "item_id": 1 }`
- `GET /bookmarks?page=1&size=20`

`GET /feeds/today` item fields include:
- `title` (original)
- `translated_title_ko` (DeepL translation when available)
- `saved`, `skipped`, `liked`, `disliked`
- `curation_action`, `preference_action`

## Environment
- `CORS_ALLOWED_ORIGINS`: comma-separated origins. Example: `https://your-app.vercel.app`
- `ADMIN_TOKEN`: bearer token for `/admin/*` routes
- `DEEPL_API_KEY`: DeepL API key. If empty, title translation is skipped.
- `DEEPL_API_URL`: default `https://api-free.deepl.com/v2/translate`
- `DEEPL_TIMEOUT_SECONDS`: default `6.0`
- `DEEPL_RETRIES`: default `1`
