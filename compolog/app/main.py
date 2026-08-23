"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import scheduler
from app.config import settings
from app.errors import register_error_handlers
from app.logging_config import get_logger, setup_logging
from app.web import routes_articles, routes_auth, routes_dashboard
from app.web.templating import templates

logger = get_logger("app")

# Navigation shown in the header. Entries are added as their module lands, so the
# menu never links to a page that does not exist yet.
NAV_ITEMS: list[tuple[str, str]] = [
    ("/", "Übersicht"),
    ("/artikel", "Artikel"),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings.ensure_directories()
    logger.info(
        "startup",
        extra={"environment": settings.environment,
               "ebay_sandbox": settings.ebay_sandbox,
               "database": settings.database_url.split("///")[-1]},
    )
    if settings.secret_key == "change-me-in-dotenv-please":
        # Loud, but not fatal in development -- fatal would make the first start
        # of a fresh checkout fail before the user ever sees the README.
        logger.warning("insecure_secret_key",
                       extra={"hint": "SECRET_KEY in der .env setzen"})

    if settings.scheduler_enabled:
        scheduler.start()
    try:
        yield
    finally:
        if settings.scheduler_enabled:
            scheduler.shutdown()
        logger.info("shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Warenwirtschaft für den eBay-Handel mit Automotive-Steckverbindern",
        version="0.1.0",
        lifespan=lifespan,
        # No public API docs: this is an internal tool reachable from the internet
        # through the tunnel, and /docs is a free map of every endpoint.
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.debug else None,
    )

    if settings.trusted_hosts != ["*"]:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)

    static_dir = Path(__file__).parent / "web" / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    templates.env.globals["nav_items"] = NAV_ITEMS

    register_error_handlers(app)

    app.include_router(routes_auth.router)
    app.include_router(routes_dashboard.router)
    app.include_router(routes_articles.router)
    return app


app = create_app()
