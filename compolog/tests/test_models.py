"""Data-model invariants that later modules will rely on."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.db import engine
from app.models import Base
from app.models.automotive import ArticleOeNumber, OeNumber, Vehicle
from app.models.base import utcnow
from app.models.catalog import Article, ArticleImage
from app.models.enums import ArticleKind, StockMovementType
from app.models.inventory import StockMovement, StorageLocation


def test_every_model_table_exists_in_the_migrated_database():
    """Catches a model that was added without a migration."""
    actual = set(inspect(engine).get_table_names())
    expected = set(Base.metadata.tables)
    missing = expected - actual
    assert not missing, f"Tabellen fehlen in der Migration: {sorted(missing)}"


def test_sku_is_unique(db):
    db.add(Article(sku="CL-DUP", title="Erster", kind=ArticleKind.STANDALONE.value))
    db.flush()
    db.add(Article(sku="CL-DUP", title="Zweiter", kind=ArticleKind.STANDALONE.value))
    with pytest.raises(IntegrityError):
        db.flush()


def test_foreign_keys_are_enforced(db):
    """SQLite ignores foreign keys unless the PRAGMA is on -- verify it is."""
    db.add(ArticleImage(article_id=999999, relative_path="nirgends.jpg"))
    with pytest.raises(IntegrityError):
        db.flush()


def test_oe_number_normalisation():
    assert OeNumber.normalise("1J0 973 722") == "1J0973722"
    assert OeNumber.normalise("1j0-973.722") == "1J0973722"
    assert OeNumber.normalise("  n 907 327 02  ") == "N90732702"


def test_same_oe_number_can_serve_several_articles(db):
    oe = OeNumber(number="1J0 973 722", normalised=OeNumber.normalise("1J0 973 722"),
                  brand="VAG")
    loose = Article(sku="CL-OE-1", title="Gehäuse einzeln",
                    kind=ArticleKind.STANDALONE.value)
    kit = Article(sku="CL-OE-2", title="Reparatursatz", kind=ArticleKind.STANDALONE.value)
    db.add_all([oe, loose, kit])
    db.flush()
    db.add_all([
        ArticleOeNumber(article_id=loose.id, oe_number_id=oe.id, is_primary=True),
        ArticleOeNumber(article_id=kit.id, oe_number_id=oe.id, is_primary=False),
    ])
    db.flush()
    assert len(oe.articles) == 2


def test_an_article_cannot_carry_the_same_oe_number_twice(db):
    oe = OeNumber(number="A1", normalised="A1", brand="MB")
    article = Article(sku="CL-OE-3", title="Test", kind=ArticleKind.STANDALONE.value)
    db.add_all([oe, article])
    db.flush()
    db.add(ArticleOeNumber(article_id=article.id, oe_number_id=oe.id))
    db.flush()
    db.add(ArticleOeNumber(article_id=article.id, oe_number_id=oe.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_variant_parent_carries_no_stock(db):
    parent = Article(sku="CL-VAR", title="Steckergehäuse Serie X",
                     kind=ArticleKind.PARENT.value, variant_axis="pin_count")
    db.add(parent)
    db.flush()
    child = Article(sku="CL-VAR-4", title="Steckergehäuse Serie X, 4-polig",
                    kind=ArticleKind.CHILD.value, parent_id=parent.id)
    db.add(child)
    db.flush()

    assert parent.carries_stock is False
    assert child.carries_stock is True
    assert child.parent is parent
    assert parent.children == [child]


def test_vehicle_display_name(db):
    vehicle = Vehicle(make="Volkswagen", model="Golf V", variant="1.9 TDI",
                      engine_code="BKC", year_from=200310, year_to=200902)
    assert vehicle.display_name == "Volkswagen Golf V 1.9 TDI BKC"


def test_stock_movement_journal_sums_to_the_running_total(db):
    """The journal is the source of truth; quantity_after must agree with it."""
    article = Article(sku="CL-MOVE", title="Test", kind=ArticleKind.STANDALONE.value)
    location = StorageLocation(code="A-01-01", name="Regal A Fach 1")
    db.add_all([article, location])
    db.flush()

    running = 0
    for movement_type, quantity in (
        (StockMovementType.GOODS_RECEIPT, 50),
        (StockMovementType.SALE, -3),
        (StockMovementType.SALE, -2),
        (StockMovementType.RETURN, 1),
        (StockMovementType.STOCKTAKE, -1),
    ):
        running += quantity
        db.add(StockMovement(
            article_id=article.id, location_id=location.id,
            movement_type=movement_type.value, quantity=quantity,
            quantity_after=running, booked_at=utcnow(),
        ))
    db.flush()

    movements = db.scalars(
        select(StockMovement).where(StockMovement.article_id == article.id)
        .order_by(StockMovement.id)
    ).all()
    assert sum(m.quantity for m in movements) == 45
    assert movements[-1].quantity_after == 45


def test_stock_movement_has_no_updated_at(db):
    """Guard rail: the journal is append-only, so it must not look mutable."""
    assert not hasattr(StockMovement, "updated_at")


def test_article_repr_is_readable(db):
    article = Article(sku="CL-REPR", title="Ein sehr langer Artikeltitel für die Anzeige",
                      kind=ArticleKind.STANDALONE.value)
    assert "CL-REPR" in repr(article)
