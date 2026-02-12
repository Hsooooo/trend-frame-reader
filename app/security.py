from fastapi import Header, HTTPException

from app.config import settings


def require_admin_token(authorization: str | None = Header(default=None)):
    token = settings.admin_token.strip()
    if not token:
        raise HTTPException(status_code=503, detail="admin_token_not_configured")

    expected = f"Bearer {token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="unauthorized")
