"""Change history (Modul 1)."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.catalog import Article
from app.models.enums import ArticleKind, AuditAction
from app.services.audit import record_changes, record_event, snapshot

TRACKED = ["title", "sales_price_gross", "is_active", "min_stock"]


def test_records_one_row_per_changed_field(db, admin_user):
    article = Article(sku="CL-AUD-1", title="Alter Titel",
                      kind=ArticleKind.STANDALONE.value,
                      sales_price_gross=Decimal("4.99"), min_stock=0)
    db.add(article)
    db.flush()

    before = snapshot(article, TRACKED)
    article.title = "Neuer Titel"
    article.sales_price_gross = Decimal("5.49")
    after = snapshot(article, TRACKED)

    assert record_changes(db, entity_type="article", entity_id=article.id,
                          before=before, after=after, user_id=admin_user.id) == 2
    db.flush()

    rows = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == article.id).order_by(AuditLog.field_name)
    ).all()
    assert [r.field_name for r in rows] == ["sales_price_gross", "title"]

    price_row = rows[0]
    assert price_row.old_value == "4.99"
    assert price_row.new_value == "5.49"
    assert price_row.user_id == admin_user.id
    assert price_row.action == AuditAction.UPDATE.value


def test_unchanged_fields_are_not_logged(db):
    article = Article(sku="CL-AUD-2", title="Titel", kind=ArticleKind.STANDALONE.value)
    db.add(article)
    db.flush()
    before = snapshot(article, TRACKED)
    assert record_changes(db, entity_type="article", entity_id=article.id,
                          before=before, after=snapshot(article, TRACKED)) == 0


def test_booleans_are_rendered_readably(db):
    article = Article(sku="CL-AUD-3", title="Titel", kind=ArticleKind.STANDALONE.value,
                      is_active=True)
    db.add(article)
    db.flush()
    before = snapshot(article, TRACKED)
    article.is_active = False
    record_changes(db, entity_type="article", entity_id=article.id,
                   before=before, after=snapshot(article, TRACKED))
    db.flush()

    row = db.scalar(select(AuditLog).where(AuditLog.field_name == "is_active"))
    assert (row.old_value, row.new_value) == ("true", "false")


def test_machine_changes_are_attributed_to_their_source(db):
    article = Article(sku="CL-AUD-4", title="Titel", kind=ArticleKind.STANDALONE.value)
    db.add(article)
    db.flush()
    record_event(db, entity_type="article", entity_id=article.id,
                 action=AuditAction.CREATE, source="ebay-sync",
                 note="aus bestehendem Angebot importiert")
    db.flush()

    row = db.scalar(select(AuditLog).where(AuditLog.entity_id == article.id))
    assert row.source == "ebay-sync"
    assert row.user_id is None
    assert row.action == AuditAction.CREATE.value
