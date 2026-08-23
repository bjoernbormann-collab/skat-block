"""Modul 1 -- Artikelverwaltung (Weboberfläche)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, File, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.errors import DomainError, NotFoundError
from app.models.audit import AuditLog
from app.models.automotive import AttributeDefinition
from app.models.catalog import Article, Manufacturer, ProductGroup, Supplier
from app.models.enums import ArticleCondition, ArticleKind, UserRole
from app.services import images as image_service
from app.services.articles import (
    compute_margin,
    create_article,
    deactivate_article,
    find_duplicates,
    get_article,
    search_articles,
    set_cross_references,
    set_oe_numbers,
    update_article,
)
from app.services.importexport import (
    FIELD_SPECS,
    ParseError,
    export_csv,
    export_xlsx,
    import_articles,
    read_table,
    suggest_mapping,
)
from app.web.templating import templates

router = APIRouter(prefix="/artikel", tags=["articles"])

PAGE_SIZE = 50


def _require_admin(user) -> None:
    """Warehouse staff may look at articles but not change master data."""
    if user.role != UserRole.ADMIN.value:
        raise DomainError("Stammdaten dürfen nur von Administratoren geändert werden.")


def _decimal_or_none(raw: str | None) -> Decimal | None:
    """Form values arrive as strings; empty means 'not set', not zero."""
    if raw is None or not raw.strip():
        return None
    text = raw.strip().replace(".", "").replace(",", ".") if "," in raw else raw.strip()
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise DomainError(f"„{raw}“ ist keine gültige Zahl.") from exc


def _form_context(db: DbSession) -> dict[str, Any]:
    return {
        "product_groups": db.scalars(select(ProductGroup).order_by(ProductGroup.name)).all(),
        "suppliers": db.scalars(
            select(Supplier).where(Supplier.is_active.is_(True)).order_by(Supplier.name)
        ).all(),
        "manufacturers": db.scalars(
            select(Manufacturer).order_by(Manufacturer.name)
        ).all(),
        "attribute_definitions": db.scalars(
            select(AttributeDefinition).order_by(AttributeDefinition.sort_order)
        ).all(),
        "parents": db.scalars(
            select(Article).where(Article.kind == ArticleKind.PARENT.value)
            .order_by(Article.sku)
        ).all(),
        "conditions": list(ArticleCondition),
        "kinds": list(ArticleKind),
    }


def _collect_article_form(form) -> dict[str, Any]:
    """Turn the posted form into a field dict the service layer understands."""
    def text(name: str, default: str = "") -> str:
        return (form.get(name) or default).strip()

    def optional_text(name: str) -> str | None:
        value = text(name)
        return value or None

    def integer(name: str) -> int | None:
        value = text(name)
        return int(value) if value.isdigit() else None

    data: dict[str, Any] = {
        "title": text("title"),
        "ean": optional_text("ean"),
        "mpn": optional_text("mpn"),
        "short_description": text("short_description"),
        "long_description": text("long_description"),
        "kind": text("kind", ArticleKind.STANDALONE.value),
        "parent_id": integer("parent_id"),
        "variant_axis": text("variant_axis"),
        "hs_code": text("hs_code"),
        "country_of_origin": text("country_of_origin").upper()[:2],
        "supplier_sku": text("supplier_sku"),
        "condition": text("condition", ArticleCondition.NEW.value),
        "internal_note": text("internal_note"),
        "manufacturer_id": integer("manufacturer_id"),
        "supplier_id": integer("supplier_id"),
        "product_group_id": integer("product_group_id"),
        "is_active": form.get("is_active") is not None,
    }
    for field in ("weight_gram", "length_mm", "width_mm", "height_mm",
                  "packaging_unit", "min_stock"):
        value = _decimal_or_none(form.get(field))
        if value is not None:
            data[field] = value.quantize(Decimal("0.001"))
    for field in ("purchase_price_net", "sales_price_gross"):
        value = _decimal_or_none(form.get(field))
        data[field] = value.quantize(Decimal("0.0001")) if value is not None else None
    vat = _decimal_or_none(form.get("vat_rate"))
    data["vat_rate"] = vat.quantize(Decimal("0.0001")) if vat is not None \
        else settings.default_vat_rate

    if not data["title"]:
        raise DomainError("Der Titel darf nicht leer sein.")
    if len(data["title"]) > 80:
        raise DomainError(
            f"Der Titel ist {len(data['title'])} Zeichen lang. eBay erlaubt "
            "höchstens 80."
        )
    return data


def _parse_pairs(form, prefix: str, count: int) -> list[list[str]]:
    """Read repeated form fields like oe_number_0, oe_brand_0, …"""
    rows: list[list[str]] = []
    for index in range(count):
        values = [
            (form.get(f"{name}_{index}") or "").strip()
            for name in prefix.split(",")
        ]
        if any(values):
            rows.append(values)
    return rows


# ------------------------------------------------------------------- list view


@router.get("")
def article_list(request: Request, db: DbSession, user: CurrentUser,
                 q: str = "", gruppe: int | None = None, seite: int = 1,
                 inaktiv: bool = False) -> Response:
    page = max(1, seite)
    articles, total = search_articles(
        db, term=q, product_group_id=gruppe, only_active=not inaktiv,
        limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE,
    )
    context = {
        "articles": articles,
        "total": total,
        "q": q,
        "gruppe": gruppe,
        "inaktiv": inaktiv,
        "page": page,
        "page_size": PAGE_SIZE,
        "page_count": max(1, -(-total // PAGE_SIZE)),
        "product_groups": db.scalars(
            select(ProductGroup).order_by(ProductGroup.name)).all(),
        "primary_image": image_service.primary_image,
    }
    # HTMX live search swaps only the result table.
    template = "articles/_table.html" if request.headers.get("hx-request") \
        else "articles/list.html"
    return templates.TemplateResponse(request, template, context)


# ------------------------------------------------------------------ detail view


@router.get("/neu")
def article_new(request: Request, db: DbSession, user: CurrentUser) -> Response:
    _require_admin(user)
    context = _form_context(db)
    context.update({"article": None, "duplicates": []})
    return templates.TemplateResponse(request, "articles/form.html", context)


@router.post("/neu")
async def article_create(request: Request, db: DbSession, user: CurrentUser) -> Response:
    _require_admin(user)
    form = await request.form()
    data = _collect_article_form(form)

    oe_rows = _parse_pairs(form, "oe_number,oe_brand", 20)
    # Duplicate check is advisory: the user can confirm and proceed.
    if form.get("ignore_duplicates") is None:
        duplicates = find_duplicates(db, mpn=data.get("mpn"),
                                     oe_numbers=[row[0] for row in oe_rows])
        if duplicates:
            context = _form_context(db)
            context.update({"article": None, "duplicates": duplicates,
                            "form_values": dict(form)})
            return templates.TemplateResponse(request, "articles/form.html", context,
                                              status_code=409)

    article = create_article(db, data, user_id=user.id)
    set_oe_numbers(db, article, [(row[0], row[1]) for row in oe_rows])
    set_cross_references(db, article,
                         [(row[0], row[1], row[2])
                          for row in _parse_pairs(form, "xref_brand,xref_number,xref_note", 20)])
    return RedirectResponse(f"/artikel/{article.id}", status_code=303)


@router.get("/export")
def article_export(db: DbSession, user: CurrentUser, format: str = "xlsx",
                   q: str = "", inaktiv: bool = False) -> Response:
    """Export the current search result, not blindly everything."""
    articles, _ = search_articles(db, term=q, only_active=not inaktiv,
                                  limit=100_000, offset=0)
    if format == "csv":
        payload = export_csv(db, articles)
        media_type = "text/csv"
        filename = "artikel.csv"
    else:
        payload = export_xlsx(db, articles)
        media_type = ("application/vnd.openxmlformats-officedocument"
                      ".spreadsheetml.sheet")
        filename = "artikel.xlsx"
    return Response(payload, media_type=media_type,
                    headers={"content-disposition":
                             f'attachment; filename="{filename}"'})


@router.get("/import")
def import_form(request: Request, db: DbSession, user: CurrentUser) -> Response:
    _require_admin(user)
    return templates.TemplateResponse(request, "articles/import.html",
                                      {"stage": "upload", "field_specs": FIELD_SPECS})


@router.post("/import")
async def import_upload(request: Request, db: DbSession, user: CurrentUser,
                        datei: Annotated[UploadFile, File()]) -> Response:
    """Step 1: read the file, propose a mapping, show a dry-run report."""
    _require_admin(user)
    payload = await datei.read()
    try:
        headers, rows = read_table(payload, datei.filename or "")
    except ParseError as exc:
        raise DomainError(str(exc)) from exc

    if not headers:
        raise DomainError("Die Datei enthält keine Kopfzeile.")

    form = await request.form()
    # A second submit carries the user-corrected mapping back in.
    mapping = {
        header: field for header, field in (
            (header, (form.get(f"map_{index}") or "").strip())
            for index, header in enumerate(headers)
        ) if field
    } or suggest_mapping(headers)

    commit = form.get("uebernehmen") is not None
    try:
        report = import_articles(db, headers=headers, rows=rows, mapping=mapping,
                                 dry_run=not commit, user_id=user.id)
    except ParseError as exc:
        raise DomainError(str(exc)) from exc

    return templates.TemplateResponse(
        request, "articles/import.html",
        {"stage": "report", "headers": headers, "mapping": mapping,
         "report": report, "field_specs": FIELD_SPECS,
         "row_count": len(rows), "filename": datei.filename},
    )


@router.get("/{article_id}")
def article_detail(request: Request, db: DbSession, user: CurrentUser,
                   article_id: int) -> Response:
    article = get_article(db, article_id)
    history = db.scalars(
        select(AuditLog)
        .where(AuditLog.entity_type == "article", AuditLog.entity_id == article_id)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(100)
    ).all()
    return templates.TemplateResponse(
        request, "articles/detail.html",
        {"article": article, "history": history,
         "margin": compute_margin(article),
         "primary": image_service.primary_image(article)},
    )


@router.get("/{article_id}/bearbeiten")
def article_edit(request: Request, db: DbSession, user: CurrentUser,
                 article_id: int) -> Response:
    _require_admin(user)
    context = _form_context(db)
    context.update({"article": get_article(db, article_id), "duplicates": []})
    return templates.TemplateResponse(request, "articles/form.html", context)


@router.post("/{article_id}/bearbeiten")
async def article_save(request: Request, db: DbSession, user: CurrentUser,
                       article_id: int) -> Response:
    _require_admin(user)
    article = get_article(db, article_id)
    form = await request.form()
    update_article(db, article, _collect_article_form(form), user_id=user.id)
    set_oe_numbers(db, article,
                   [(row[0], row[1]) for row in _parse_pairs(form, "oe_number,oe_brand", 20)])
    set_cross_references(db, article,
                         [(row[0], row[1], row[2])
                          for row in _parse_pairs(form, "xref_brand,xref_number,xref_note", 20)])
    return RedirectResponse(f"/artikel/{article.id}", status_code=303)


@router.post("/{article_id}/deaktivieren")
def article_deactivate(db: DbSession, user: CurrentUser, article_id: int) -> Response:
    _require_admin(user)
    deactivate_article(db, get_article(db, article_id), user_id=user.id)
    return RedirectResponse(f"/artikel/{article_id}", status_code=303)


# ---------------------------------------------------------------------- images


@router.post("/{article_id}/bilder")
async def image_upload(request: Request, db: DbSession, user: CurrentUser,
                       article_id: int,
                       bilder: Annotated[list[UploadFile], File()]) -> Response:
    _require_admin(user)
    article = get_article(db, article_id)
    for upload in bilder:
        payload = await upload.read()
        if payload:
            image_service.add_image(db, article, data=payload,
                                    original_filename=upload.filename or "")
    return RedirectResponse(f"/artikel/{article_id}", status_code=303)


@router.post("/{article_id}/bilder/{image_id}/hauptbild")
def image_make_primary(db: DbSession, user: CurrentUser, article_id: int,
                       image_id: int) -> Response:
    _require_admin(user)
    image_service.set_primary(db, get_article(db, article_id), image_id)
    return RedirectResponse(f"/artikel/{article_id}", status_code=303)


@router.post("/{article_id}/bilder/{image_id}/loeschen")
def image_delete(db: DbSession, user: CurrentUser, article_id: int,
                 image_id: int) -> Response:
    _require_admin(user)
    image_service.delete_image(db, get_article(db, article_id), image_id)
    return RedirectResponse(f"/artikel/{article_id}", status_code=303)


@router.get("/{article_id}/bilder/{image_id}/datei")
def image_file(db: DbSession, user: CurrentUser, article_id: int,
               image_id: int) -> Response:
    """Serve an image through the app rather than mounting the directory.

    Mounting settings.image_dir as static would make every product photo public
    to anyone who reaches the tunnel, logged in or not.
    """
    article = get_article(db, article_id)
    image = next((candidate for candidate in article.images
                  if candidate.id == image_id), None)
    if image is None:
        raise NotFoundError("Bild nicht gefunden.")
    path = settings.image_dir / image.relative_path
    if not path.is_file():
        raise NotFoundError("Bilddatei fehlt auf der Festplatte.")
    return FileResponse(path, media_type=image.content_type)
