# trend-frame-reader

Phase 2.5 backend for Trend x Frame Reader. Includes bookmark Knowledge Graph and Mini-RAG Q&A.

## Stack
- FastAPI
- PostgreSQL + SQLAlchemy
- MongoDB Atlas (Knowledge Graph + Vector Search)
- APScheduler
- OpenAI (keyword extraction, embeddings, RAG)

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
- `POST /admin/backfill-graph` — 기존 북마크를 MongoDB 그래프/벡터로 전체 백필 (requires `Authorization: Bearer <ADMIN_TOKEN>`)
- `GET /feeds/today?slot=am|pm`
- `POST /feedback` with `{ "item_id": 1, "action": "saved|skipped|liked|disliked" }`
- `POST /events/click` with `{ "item_id": 1 }`
- `GET /bookmarks?page=1&size=20`
- `POST /bookmarks/ask` with `{ "query": "...", "top_k": 5 }` — 북마크 기반 Mini-RAG Q&A
- `GET /bookmarks/explore?keyword=AI&depth=1` — 키워드 그래프 탐색
- `GET /bookmarks/keywords?limit=30` — 북마크 키워드 클라우드

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
- `OPENAI_API_KEY`: OpenAI API key (keyword extraction, embeddings, RAG)
- `OPENAI_KEYWORD_MODEL`: default `gpt-4o-mini`
- `OPENAI_EMBEDDING_MODEL`: default `text-embedding-3-small`
- `MONGODB_URI`: MongoDB Atlas connection string. If empty, graph/RAG features are disabled.
- `MONGODB_DATABASE`: default `trend_frame_graph`
- `RAG_TOP_K`: number of bookmarks to retrieve for RAG context, default `5`
- `GRAPH_BACKFILL_BATCH_SIZE`: backfill batch size, default `50`

## Phase 2.5 Setup (Knowledge Graph + Mini-RAG)

1. MongoDB Atlas M0 클러스터 생성 후 `.env`에 `MONGODB_URI` 설정
2. Atlas UI에서 `articles` 컬렉션에 Vector Search 인덱스 생성:
   ```json
   {
     "type": "vectorSearch",
     "definition": {
       "fields": [{ "type": "vector", "numDimensions": 1536, "path": "embedding", "similarity": "cosine" }]
     }
   }
   ```
   인덱스명: `vector_index`
3. 기존 북마크 백필: `POST /admin/backfill-graph`
4. Q&A 테스트: `POST /bookmarks/ask { "query": "최근 AI 관련 뉴스 요약해줘" }`
