from __future__ import annotations

from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Feedback, ItemEvent, User


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

ALGORITHM = "HS256"


def create_jwt(user_id: int) -> str:
    expire = datetime.now(UTC) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def decode_jwt(token: str) -> int:
    """Decode token and return user_id. Raises JWTError on failure."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    sub = payload.get("sub")
    if sub is None:
        raise JWTError("missing sub")
    return int(sub)


# ---------------------------------------------------------------------------
# Google OAuth
# ---------------------------------------------------------------------------

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"


def build_google_auth_url(state: str | None = None) -> str:
    params: dict[str, str] = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    if state:
        params["state"] = state

    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def exchange_google_code(code: str) -> dict:
    """Exchange authorization code for user info. Returns dict with google_id, email, name, picture."""
    with httpx.Client(timeout=10.0) as client:
        token_resp = client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        access_token = token_data["access_token"]

        userinfo_resp = client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        userinfo_resp.raise_for_status()
        info = userinfo_resp.json()

    return {
        "google_id": info["sub"],
        "email": info["email"],
        "name": info.get("name", info["email"]),
        "picture": info.get("picture"),
    }


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def get_or_create_user(db: Session, google_info: dict) -> tuple[User, bool]:
    """Return (user, is_new). First ever user gets is_owner=True."""
    from sqlalchemy import select, func

    existing = db.execute(
        select(User).where(User.google_id == google_info["google_id"])
    ).scalar_one_or_none()

    if existing:
        return existing, False

    # Check if this is the very first user
    user_count = db.execute(select(func.count()).select_from(User)).scalar_one()
    is_owner = user_count == 0

    user = User(
        google_id=google_info["google_id"],
        email=google_info["email"],
        name=google_info["name"],
        picture=google_info.get("picture"),
        is_owner=is_owner,
    )
    db.add(user)
    db.flush()  # get user.id without full commit
    return user, True


def migrate_owner_data(db: Session, user_id: int) -> None:
    """Assign all existing ownerless feedback/events to the first user (owner)."""
    from sqlalchemy import update

    db.execute(
        update(Feedback)
        .where(Feedback.user_id.is_(None))
        .values(user_id=user_id)
    )
    db.execute(
        update(ItemEvent)
        .where(ItemEvent.user_id.is_(None))
        .values(user_id=user_id)
    )

    # MongoDB: mark existing articles with user_id
    try:
        from app.mongo import get_articles_collection
        articles_col = get_articles_collection()
        if articles_col is not None:
            articles_col.update_many(
                {"user_id": {"$exists": False}},
                {"$set": {"user_id": user_id}},
            )
    except Exception:
        import logging
        logging.getLogger(__name__).warning("MongoDB owner migration failed (non-fatal)", exc_info=True)
