"""Login / logout."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request, Response
from fastapi.responses import RedirectResponse

from app.config import settings
from app.deps import CurrentUser, DbSession, OptionalUser
from app.logging_config import get_logger
from app.security import authenticate, create_session, revoke_session
from app.web.templating import templates

router = APIRouter(tags=["auth"])
logger = get_logger("auth")


def _safe_next(target: str | None) -> str:
    """Only allow same-site relative redirects -- never bounce to another host."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return "/"
    return target


@router.get("/login")
def login_form(request: Request, user: OptionalUser, next: str = "/") -> Response:
    if user is not None:
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(
        request, "auth/login.html", {"next": _safe_next(next), "error": None}
    )


@router.post("/login")
def login_submit(
    request: Request,
    db: DbSession,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str, Form()] = "/",
) -> Response:
    user = authenticate(db, username.strip(), password)
    if user is None:
        # One message for every failure mode: no hints about which usernames exist.
        logger.warning("login_failed", extra={"username": username[:64],
                                              "ip": request.client.host if request.client else ""})
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"next": _safe_next(next), "error": "Benutzername oder Passwort ist falsch."},
            status_code=401,
        )

    session_row = create_session(
        db, user,
        user_agent=request.headers.get("user-agent", ""),
        ip_address=request.client.host if request.client else "",
    )
    logger.info("login_ok", extra={"user_id": user.id, "username": user.username})
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        settings.session_cookie_name,
        session_row.token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: DbSession, user: CurrentUser) -> Response:
    revoke_session(db, request.cookies.get(settings.session_cookie_name))
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response
