"""Modul 1 -- Artikelverwaltung: create, update, search, duplicate detection.

All writes go through here rather than through the routes, for three reasons:
the SKU has to come from the number range, the change history has to be written
in the same transaction as the change itself, and the variant rules (a parent
carries no stock, a child must have a parent) have to hold no matter whether the
caller is a form, an importer or the eBay sync.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import DomainError, NotFoundError
from app.models.automotive import ArticleOeNumber, CrossReference, OeNumber
from app.models.catalog import Article
from app.models.enums import ArticleKind, AuditAction
from app.services.audit import record_changes, record_event, snapshot
from app.services.numbering import next_number

# Fields whose changes are worth a history entry. Deliberately a whitelist:
# logging every column would bury the price change that actually matters.
TRACKED_FIELDS = [
    "sku", "ean", "mpn", "manufacturer_id", "title", "short_description",
    "long_description", "kind", "parent_id", "variant_axis", "weight_gram",
    "length_mm", "width_mm", "height_mm", "packaging_unit", "hs_code",
    "country_of_origin", "purchase_price_net", "sales_price_gross", "vat_rate",
    "supplier_id", "supplier_sku", "product_group_id", "condition", "min_stock",
    "is_active", "internal_note",
]


def normalise_part_number(raw: str | None) -> str:
    """Same rule as OeNumber.normalise -- MPNs suffer from the same formatting
    chaos ('MG 641 234' vs 'MG641234')."""
    return OeNumber.normalise(raw) if raw else ""


# ---------------------------------------------------------------- duplicates

class DuplicateCandidate:
    """One possible duplicate, with the reason it was flagged."""

    def __init__(self, article: Article, reason: str, matched_value: str) -> None:
        self.article = article
        self.reason = reason
        self.matched_value = matched_value


def find_duplicates(
    db: Session,
    *,
    mpn: str | None = None,
    oe_numbers: list[str] | None = None,
    exclude_article_id: int | None = None,
) -> list[DuplicateCandidate]:
    """Look for existing articles that might already be this part.

    Matches on the normalised MPN and on any of the given OE numbers. Returns
    candidates rather than blocking: two genuinely different parts can share an
    OE number, so this is a warning for a human, never an automatic rejection.
    """
    candidates: dict[int, DuplicateCandidate] = {}

    normalised_mpn = normalise_part_number(mpn)
    if normalised_mpn:
        # No normalised MPN column exists (yet), so the comparison happens in
        # Python over a coarse LIKE prefilter. At a few thousand articles this is
        # comfortably fast; if the catalogue grows past ~50k, add a stored
        # normalised column with an index rather than making this cleverer.
        rough = normalised_mpn[:4]
        stmt = select(Article).where(Article.mpn.is_not(None))
        if rough:
            stmt = stmt.where(Article.mpn.ilike(f"%{rough[0]}%"))
        for article in db.scalars(stmt):
            if article.id == exclude_article_id:
                continue
            if normalise_part_number(article.mpn) == normalised_mpn:
                candidates[article.id] = DuplicateCandidate(
                    article, "Gleiche Herstellerteilenummer", article.mpn or ""
                )

    for raw in oe_numbers or []:
        normalised = OeNumber.normalise(raw)
        if not normalised:
            continue
        stmt = (
            select(Article)
            .join(ArticleOeNumber, ArticleOeNumber.article_id == Article.id)
            .join(OeNumber, OeNumber.id == ArticleOeNumber.oe_number_id)
            .where(OeNumber.normalised == normalised)
        )
        for article in db.scalars(stmt).unique():
            if article.id == exclude_article_id or article.id in candidates:
                continue
            candidates[article.id] = DuplicateCandidate(
                article, "Gleiche OE-Nummer", raw
            )

    return list(candidates.values())


# ------------------------------------------------------------------- search

def build_search_query(
    db: Session,
    *,
    term: str = "",
    product_group_id: int | None = None,
    supplier_id: int | None = None,
    only_active: bool = True,
    include_variant_parents: bool = True,
) -> Select:
    """Search over SKU, MPN, title, EAN, OE number and cross reference.

    Implemented as LIKE across a few joined tables. That is honest about what it
    is: fine for the low thousands of articles this system is sized for, and it
    needs no extra index maintenance. The upgrade path when it stops being fast
    is SQLite FTS5 (or a tsvector on PostgreSQL) over a denormalised search
    column -- not a smarter LIKE.
    """
    stmt = select(Article)
    if only_active:
        stmt = stmt.where(Article.is_active.is_(True))
    if product_group_id is not None:
        stmt = stmt.where(Article.product_group_id == product_group_id)
    if supplier_id is not None:
        stmt = stmt.where(Article.supplier_id == supplier_id)
    if not include_variant_parents:
        stmt = stmt.where(Article.kind != ArticleKind.PARENT.value)

    term = term.strip()
    if term:
        pattern = f"%{term}%"
        normalised = OeNumber.normalise(term)

        oe_match = (
            select(ArticleOeNumber.article_id)
            .join(OeNumber, OeNumber.id == ArticleOeNumber.oe_number_id)
            .where(OeNumber.normalised.like(f"%{normalised}%"))
        )
        cross_match = (
            select(CrossReference.article_id)
            .where(CrossReference.normalised.like(f"%{normalised}%"))
        )
        stmt = stmt.where(
            or_(
                Article.sku.ilike(pattern),
                Article.mpn.ilike(pattern),
                Article.title.ilike(pattern),
                Article.ean.ilike(pattern),
                Article.id.in_(oe_match),
                Article.id.in_(cross_match),
            )
        )
    return stmt.order_by(Article.sku)


def search_articles(db: Session, *, limit: int = 50, offset: int = 0,
                    **filters: Any) -> tuple[list[Article], int]:
    """Returns (page, total). Total is a separate COUNT so the pager is honest."""
    stmt = build_search_query(db, **filters)
    total = db.scalar(
        select(func.count()).select_from(stmt.order_by(None).subquery())
    ) or 0
    page = db.scalars(
        stmt.options(
            selectinload(Article.images),
            selectinload(Article.product_group),
            selectinload(Article.manufacturer),
        ).limit(limit).offset(offset)
    ).unique().all()
    return list(page), total


def get_article(db: Session, article_id: int) -> Article:
    article = db.get(Article, article_id)
    if article is None:
        raise NotFoundError(f"Artikel mit der ID {article_id} existiert nicht.")
    return article


def get_by_sku(db: Session, sku: str) -> Article | None:
    return db.scalar(select(Article).where(Article.sku == sku))


# -------------------------------------------------------------------- writes

def allocate_sku(db: Session) -> str:
    """Next SKU from the number range. Must run in the caller's transaction."""
    return next_number(db, "sku")


def _validate_variant_rules(db: Session, article: Article) -> None:
    """A parent groups, a child belongs, and neither may nest.

    Enforced here rather than by a database constraint because the rule spans
    rows (a child's parent must itself be a parent), which SQLite cannot express
    as a CHECK.
    """
    if article.kind == ArticleKind.CHILD.value:
        if article.parent_id is None:
            raise DomainError("Ein Variantenartikel braucht einen Elternartikel.")
        parent = db.get(Article, article.parent_id)
        if parent is None:
            raise DomainError("Der angegebene Elternartikel existiert nicht.")
        if parent.kind != ArticleKind.PARENT.value:
            raise DomainError(
                f"Artikel {parent.sku} ist kein Elternartikel und kann keine "
                "Varianten tragen."
            )
        if parent.id == article.id:
            raise DomainError("Ein Artikel kann nicht sein eigener Elternartikel sein.")
    elif article.parent_id is not None:
        raise DomainError(
            "Nur Artikel der Art „Variante“ dürfen einen Elternartikel haben."
        )

    if article.id is not None and article.kind != ArticleKind.PARENT.value:
        # Demoting a parent that still has children would orphan them.
        child_count = db.scalar(
            select(func.count()).select_from(Article)
            .where(Article.parent_id == article.id)
        ) or 0
        if child_count:
            raise DomainError(
                f"Artikel hat noch {child_count} Varianten und kann deshalb nicht "
                "als Elternartikel entfernt werden."
            )


def create_article(
    db: Session,
    data: dict[str, Any],
    *,
    user_id: int | None = None,
    source: str = "web",
) -> Article:
    """Create an article. SKU is allocated if not supplied."""
    payload = dict(data)
    sku = (payload.pop("sku", "") or "").strip()
    if not sku:
        sku = allocate_sku(db)
    elif get_by_sku(db, sku) is not None:
        raise DomainError(f"Die Artikelnummer {sku} ist bereits vergeben.")

    article = Article(sku=sku, created_by_id=user_id, updated_by_id=user_id)
    for field, value in payload.items():
        if hasattr(article, field):
            setattr(article, field, value)
    article.kind = article.kind or ArticleKind.STANDALONE.value

    _validate_variant_rules(db, article)
    db.add(article)
    db.flush()

    record_event(db, entity_type="article", entity_id=article.id,
                 action=AuditAction.CREATE, user_id=user_id, source=source,
                 note=f"{article.sku} – {article.title}")
    return article


def update_article(
    db: Session,
    article: Article,
    data: dict[str, Any],
    *,
    user_id: int | None = None,
    source: str = "web",
) -> int:
    """Apply changes and log every one of them. Returns the number of changes."""
    before = snapshot(article, TRACKED_FIELDS)

    for field, value in data.items():
        if field in TRACKED_FIELDS and hasattr(article, field):
            setattr(article, field, value)
    article.updated_by_id = user_id

    _validate_variant_rules(db, article)
    db.flush()

    after = snapshot(article, TRACKED_FIELDS)
    return record_changes(db, entity_type="article", entity_id=article.id,
                          before=before, after=after, user_id=user_id, source=source)


def deactivate_article(db: Session, article: Article, *,
                       user_id: int | None = None) -> None:
    """Articles are deactivated, never deleted.

    A deleted article would take its stock journal and its order history with it,
    and both have to stay readable for the retention period.
    """
    if not article.is_active:
        return
    update_article(db, article, {"is_active": False}, user_id=user_id)


# ------------------------------------------------------- OE numbers / cross refs

def set_oe_numbers(db: Session, article: Article,
                   entries: list[tuple[str, str]]) -> None:
    """Replace an article's OE numbers with ``[(number, brand), …]``.

    OeNumber rows are shared between articles, so they are looked up or created
    rather than duplicated; the link row is what gets replaced.

    Deletion goes through an explicit query, not through article.oe_numbers: the
    new links are added as plain rows rather than appended to the relationship,
    so the loaded collection is stale and iterating it would silently leave the
    previous set in place.
    """
    db.execute(
        delete(ArticleOeNumber).where(ArticleOeNumber.article_id == article.id)
    )
    db.flush()

    seen: set[str] = set()
    for index, (raw_number, brand) in enumerate(entries):
        number = (raw_number or "").strip()
        if not number:
            continue
        normalised = OeNumber.normalise(number)
        if normalised in seen:
            continue
        seen.add(normalised)

        oe = db.scalar(
            select(OeNumber).where(OeNumber.normalised == normalised,
                                   OeNumber.brand == (brand or ""))
        )
        if oe is None:
            oe = OeNumber(number=number, normalised=normalised, brand=brand or "")
            db.add(oe)
            db.flush()
        db.add(ArticleOeNumber(article_id=article.id, oe_number_id=oe.id,
                               is_primary=index == 0))
    db.flush()
    # The relationship was bypassed on both sides; drop the cached collection so
    # the caller sees what is actually in the database.
    db.expire(article, ["oe_numbers"])


def set_cross_references(db: Session, article: Article,
                         entries: list[tuple[str, str, str]]) -> None:
    """Replace cross references with ``[(brand, number, note), …]``.

    Same stale-collection caveat as set_oe_numbers -- delete by query, expire
    afterwards.
    """
    db.execute(
        delete(CrossReference).where(CrossReference.article_id == article.id)
    )
    db.flush()

    seen: set[tuple[str, str]] = set()
    for brand, number, note in entries:
        brand = (brand or "").strip()
        number = (number or "").strip()
        if not brand or not number:
            continue
        normalised = OeNumber.normalise(number)
        if (brand, normalised) in seen:
            continue
        seen.add((brand, normalised))
        db.add(CrossReference(article_id=article.id, brand=brand,
                              reference_number=number, normalised=normalised,
                              note=note or ""))
    db.flush()
    db.expire(article, ["cross_references"])


def compute_margin(article: Article) -> Decimal | None:
    """Gross margin in percent from the article's own prices.

    Uses average_cost_net when available (what the stock actually cost) and falls
    back to the list purchase price. Returns None when either side is unknown --
    a made-up margin is worse than no margin.
    """
    cost = article.average_cost_net or article.purchase_price_net
    net_price = article.sales_price_net
    if cost is None or net_price is None or net_price == 0:
        return None
    return ((net_price - cost) / net_price * Decimal(100)).quantize(Decimal("0.01"))
