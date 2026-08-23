"""Domain exceptions and the German-language error pages.

Rule: the user never sees a stack trace. Every unhandled exception is logged in
full and rendered as a short, plain German message with a reference id the user
can quote when asking what went wrong.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.logging_config import get_logger

logger = get_logger("web")


class DomainError(Exception):
    """Business rule violation -- shown to the user as-is, so write it in German."""

    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND


class PermissionDeniedError(DomainError):
    status_code = status.HTTP_403_FORBIDDEN


class ImmutableRecordError(DomainError):
    """Attempt to change a finalised document or a booked stock movement."""


STATUS_TEXTS = {
    400: ("Ungültige Eingabe", "Die Anfrage konnte nicht verarbeitet werden."),
    401: ("Nicht angemeldet", "Bitte melden Sie sich an, um fortzufahren."),
    403: ("Kein Zugriff", "Ihre Rolle erlaubt diesen Vorgang nicht."),
    404: ("Nicht gefunden", "Die aufgerufene Seite oder der Datensatz existiert nicht."),
    405: ("Nicht erlaubt", "Diese Aktion ist hier nicht möglich."),
    409: ("Konflikt", "Der Datensatz wurde zwischenzeitlich verändert."),
    422: ("Eingabe unvollständig", "Bitte prüfen Sie die markierten Felder."),
    500: ("Interner Fehler", "Es ist ein unerwarteter Fehler aufgetreten."),
}


def _wants_html(request: Request) -> bool:
    """HTML unless the caller explicitly asked for JSON.

    Defaulting to HTML rather than sniffing for "text/html" in Accept: this is a
    server-rendered application, JSON is the exception, and a client that sends
    Accept: */* (curl, fetch(), the health probe) should still get a usable page
    rather than a raw JSON blob.
    """
    accept = request.headers.get("accept", "")
    return not (accept.startswith("application/json") or accept == "application/json")


def register_error_handlers(app) -> None:
    from app.web.templating import templates

    def _render(request: Request, code: int, headline: str, detail: str,
                reference: str | None = None) -> Response:
        if not _wants_html(request):
            body = {"error": headline, "detail": detail}
            if reference:
                body["reference"] = reference
            return JSONResponse(body, status_code=code)
        # HTMX swaps a fragment into the page instead of replacing it, so error
        # responses to HTMX requests must be fragments too.
        template = "errors/fragment.html" if request.headers.get("hx-request") \
            else "errors/error.html"
        return templates.TemplateResponse(
            request, template,
            {"code": code, "headline": headline, "detail": detail,
             "reference": reference},
            status_code=code,
        )

    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> Response:
        headline, _ = STATUS_TEXTS.get(exc.status_code, STATUS_TEXTS[400])
        # NB: the key must not be "message" -- logging refuses to overwrite a
        # LogRecord attribute and raises KeyError instead of logging.
        logger.info("domain_error", extra={"path": request.url.path,
                                           "detail": exc.message})
        return _render(request, exc.status_code, headline, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> Response:
        code = exc.status_code
        headline, detail = STATUS_TEXTS.get(code, ("Fehler", str(exc.detail)))
        if isinstance(exc.detail, str) and exc.detail and code not in (404, 405):
            detail = exc.detail
        if code == status.HTTP_401_UNAUTHORIZED and _wants_html(request):
            # Bounce to the login form instead of showing a dead end.
            from fastapi.responses import RedirectResponse

            target = quote(request.url.path, safe="/")
            login_url = f"/login?next={target}"
            if request.headers.get("hx-request"):
                # HTMX swallows a 303 and swaps the login page into a fragment.
                # HX-Redirect makes the browser navigate for real instead.
                response = Response(status_code=status.HTTP_204_NO_CONTENT)
                response.headers["HX-Redirect"] = login_url
                return response
            return RedirectResponse(login_url, status_code=303)
        return _render(request, code, headline, detail)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> Response:
        reference = uuid.uuid4().hex[:12]
        logger.exception(
            "unhandled_exception",
            extra={"reference": reference, "path": request.url.path,
                   "method": request.method},
        )
        headline, detail = STATUS_TEXTS[500]
        return _render(request, 500, headline, detail, reference)


__all__ = [
    "DomainError",
    "HTTPException",
    "ImmutableRecordError",
    "NotFoundError",
    "PermissionDeniedError",
    "register_error_handlers",
]
