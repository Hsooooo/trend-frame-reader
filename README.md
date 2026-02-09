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
- `POST /admin/run-ingestion`
- `POST /admin/generate-feed/am|pm`
- `GET /feeds/today?slot=am|pm`
- `POST /feedback` with `{ "item_id": 1, "action": "saved" }`
- `GET /bookmarks`
