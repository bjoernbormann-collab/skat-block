"""Dashboard (Modul 8) -- skeleton.

STUB NOTICE: the tiles below render live counts where the underlying table
already exists, and show an explicit "noch nicht angebunden" state where the
module has not been built yet. Nothing here fakes a number.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from app.deps import CurrentUser, DbSession
from app.models.catalog import Article
from app.models.ebay import SyncTask
from app.models.enums import OrderStatus, TaskStatus
from app.models.orders import Order
from app.web.templating import templates

router = APIRouter(tags=["dashboard"])


@router.get("/")
def dashboard(request: Request, db: DbSession, user: CurrentUser) -> Response:
    open_states = (
        OrderStatus.NEW.value,
        OrderStatus.PAID.value,
        OrderStatus.PICKING.value,
        OrderStatus.PICKED.value,
    )
    stats = {
        "articles_total": db.scalar(
            select(func.count()).select_from(Article).where(Article.is_active.is_(True))
        ) or 0,
        "orders_open": db.scalar(
            select(func.count()).select_from(Order).where(Order.status.in_(open_states))
        ) or 0,
        "orders_clarification": db.scalar(
            select(func.count()).select_from(Order)
            .where(Order.status == OrderStatus.CLARIFICATION.value)
        ) or 0,
        "sync_failed": db.scalar(
            select(func.count()).select_from(SyncTask)
            .where(SyncTask.status.in_((TaskStatus.FAILED.value, TaskStatus.DEAD.value)))
        ) or 0,
    }
    return templates.TemplateResponse(request, "dashboard/index.html", {"stats": stats})


@router.get("/health")
def health(db: DbSession) -> dict:
    """Liveness probe -- also verifies the database actually answers."""
    db.execute(select(1))
    return {"status": "ok"}
