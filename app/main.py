import time

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from sqlalchemy.exc import OperationalError

from app.db import Base, engine, SessionLocal
from app.models import SlotType, Source, SourceType
from app.routers.bookmarks import router as bookmarks_router
from app.routers.feedback import router as feedback_router
from app.routers.feeds import router as feeds_router
from app.routers.health import router as health_router
from app.services.feed_builder import generate_feed_for_slot
from app.services.ingestion import run_ingestion
from app.tasks import start_scheduler, stop_scheduler

app = FastAPI(title=settings.app_name)

allowed_origins = settings.cors_origins()
if allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def require_admin_token(authorization: str | None = Header(default=None)):
    token = settings.admin_token.strip()
    if not token:
        raise HTTPException(status_code=503, detail="admin_token_not_configured")

    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.on_event("startup")
def on_startup():
    # Wait briefly for DB readiness to avoid race on container startup.
    for _ in range(20):
        try:
            Base.metadata.create_all(bind=engine)
            break
        except OperationalError:
            time.sleep(1)
    else:
        raise RuntimeError("database_not_ready")

    with SessionLocal() as db:
        # Seed minimal sources once.
        if db.query(Source).count() == 0:
            db.add_all(
                [
                    Source(type=SourceType.HN, name="Hacker News", url="https://news.ycombinator.com/", weight=1.1),
                    Source(type=SourceType.RSS, name="OpenAI Blog", url="https://openai.com/blog/rss.xml", weight=1.0),
                ]
            )
            db.commit()
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


@app.post("/admin/run-ingestion")
def admin_run_ingestion(_: None = Depends(require_admin_token)):
    with SessionLocal() as db:
        return run_ingestion(db)


@app.post("/admin/generate-feed/{slot}")
def admin_generate_feed(slot: str, _: None = Depends(require_admin_token)):
    slot_l = slot.lower()
    if slot_l not in {"am", "pm"}:
        return {"error": "invalid_slot", "allowed": ["am", "pm"]}
    slot_t = SlotType.AM if slot_l == "am" else SlotType.PM
    with SessionLocal() as db:
        feed_id = generate_feed_for_slot(db, slot_t)
    return {"feed_id": feed_id, "slot": slot_t.value}


app.include_router(health_router)
app.include_router(feeds_router)
app.include_router(feedback_router)
app.include_router(bookmarks_router)
