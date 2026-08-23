"""FastAPI dependencies: current user and role gates."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.errors import HTTPException
from app.models.auth import User
from app.models.enums import UserRole
from app.security import resolve_session

DbSession = Annotated[Session, Depends(get_db)]


def current_user_optional(request: Request, db: DbSession) -> User | None:
    token = request.cookies.get(settings.session_cookie_name)
    user = resolve_session(db, token)
    # Stash it so templates and the error handler can reach it without a second
    # database round trip.
    request.state.user = user
    return user


def current_user(
    user: Annotated[User | None, Depends(current_user_optional)],
) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Nicht angemeldet")
    return user


def require_admin(user: Annotated[User, Depends(current_user)]) -> User:
    if user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Diese Funktion ist Administratoren vorbehalten.")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(current_user_optional)]
AdminUser = Annotated[User, Depends(require_admin)]
