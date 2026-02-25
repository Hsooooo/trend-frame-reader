from fastapi import Depends, HTTPException, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.services.auth import decode_jwt


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("auth_token")
    if not token:
        raise HTTPException(status_code=401, detail="not_authenticated")
    try:
        user_id = decode_jwt(token)
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="invalid_token")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="user_not_found")
    return user


def get_optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get("auth_token")
    if not token:
        return None
    try:
        user_id = decode_jwt(token)
    except (JWTError, ValueError):
        return None
    return db.get(User, user_id)


def require_owner(user: User = Depends(get_current_user)) -> User:
    if not user.is_owner:
        raise HTTPException(status_code=403, detail="owner_required")
    return user
