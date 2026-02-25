from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.security import get_optional_user
from app.models import User
from app.services.auth import (
    build_google_auth_url,
    create_jwt,
    exchange_google_code,
    get_or_create_user,
    migrate_owner_data,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "auth_token"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days


@router.get("/google/login")
def google_login(redirect_to: str | None = Query(default=None)):
    """Redirect to Google OAuth authorization page."""
    if not settings.google_client_id:
        raise HTTPException(status_code=503, detail="google_oauth_not_configured")
    state = redirect_to or ""
    url = build_google_auth_url(state=state or None)
    return RedirectResponse(url=url)


@router.get("/google/callback")
def google_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Handle Google OAuth callback: exchange code, issue JWT, set cookie."""
    if error:
        logger.warning("Google OAuth error: %s", error)
        return RedirectResponse(url=f"{settings.frontend_url}?auth_error={error}")

    if not code:
        raise HTTPException(status_code=400, detail="missing_code")

    try:
        google_info = exchange_google_code(code)
    except Exception as exc:
        logger.error("Google code exchange failed: %s", exc)
        raise HTTPException(status_code=502, detail="google_exchange_failed") from exc

    user, is_new = get_or_create_user(db, google_info)

    if is_new and user.is_owner:
        migrate_owner_data(db, user.id)

    db.commit()

    jwt_token = create_jwt(user.id)

    # Determine redirect destination (restrict to trusted frontend origin)
    trusted = settings.frontend_url.rstrip("/")
    if state and state.startswith(trusted):
        redirect_to = state
    else:
        redirect_to = settings.frontend_url

    _secure = settings.google_redirect_uri.startswith("https")

    response = RedirectResponse(url=redirect_to)
    response.set_cookie(
        key=_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        samesite="lax",
        secure=_secure,
        max_age=_COOKIE_MAX_AGE,
    )
    return response


@router.get("/me")
def get_me(user: User | None = Depends(get_optional_user)):
    """Return current user info, or null if not authenticated."""
    if user is None:
        return None
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "picture": user.picture,
        "is_owner": user.is_owner,
    }


@router.post("/logout")
def logout(response: Response):
    """Clear auth cookie."""
    _secure = settings.google_redirect_uri.startswith("https")
    response.delete_cookie(key=_COOKIE_NAME, httponly=True, samesite="lax", secure=_secure)
    return {"ok": True}
