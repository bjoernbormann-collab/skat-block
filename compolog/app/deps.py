"""FastAPI dependencies: current user and role gates."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True)
class SessionUser:
    """Detached snapshot of the logged-in user, for templates.

    Templates must NOT be handed the ORM object. When a request raises, the
    request-scoped session is rolled back and closed before the error page is
    rendered; touching an attribute of the ORM User at that point expires it,
    hits a dead session and raises DetachedInstanceError -- turning every
    friendly German 400 page into a 500. A plain frozen snapshot cannot do that.
    """

    id: int
    username: str
    full_name: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == UserRole.ADMIN.value

    @classmethod
    def of(cls, user: User) -> "SessionUser":
        return cls(id=user.id, username=user.username,
                   full_name=user.full_name, role=user.role)


def current_user_optional(request: Request, db: DbSession) -> User | None:
    token = request.cookies.get(settings.session_cookie_name)
    user = resolve_session(db, token)
    # Templates and the error handler read this; it is a detached snapshot on
    # purpose (see SessionUser).
    request.state.user = SessionUser.of(user) if user is not None else None
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
