"""Modul 1 -- Artikelservice: SKU-Vergabe, Varianten, Duplikate, Suche."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.errors import DomainError, NotFoundError
from app.models.audit import AuditLog
from app.models.automotive import OeNumber
from app.models.catalog import Article, Manufacturer, ProductGroup
from app.models.enums import ArticleKind
from app.services.articles import (
    compute_margin,
    create_article,
    deactivate_article,
    find_duplicates,
    get_article,
    normalise_part_number,
    search_articles,
    set_cross_references,
    set_oe_numbers,
    update_article,
)


def _article(db, **overrides):
    data = {"title": "Steckergehäuse 4-polig", "kind": ArticleKind.STANDALONE.value}
    data.update(overrides)
    return create_article(db, data)


# ----------------------------------------------------------------- SKU / create

def test_sku_is_allocated_from_the_number_range(db):
    first = _article(db)
    second = _article(db, title="Zweiter Artikel")
    assert first.sku == "CL-001001"
    assert second.sku == "CL-001002"


def test_explicit_sku_is_honoured(db):
    article = _article(db, sku="CL-EIGEN-1")
    assert article.sku == "CL-EIGEN-1"


def test_duplicate_sku_is_refused(db):
    _article(db, sku="CL-DOPPELT")
    with pytest.raises(DomainError, match="bereits vergeben"):
        _article(db, sku="CL-DOPPELT", title="Anderer Artikel")


def test_creation_is_recorded_in_the_history(db, admin_user):
    article = create_article(db, {"title": "Testartikel"}, user_id=admin_user.id)
    db.flush()
    entry = db.scalar(
        select(AuditLog).where(AuditLog.entity_type == "article",
                               AuditLog.entity_id == article.id)
    )
    assert entry.action == "create"
    assert entry.user_id == admin_user.id


def test_get_article_raises_for_unknown_id(db):
    with pytest.raises(NotFoundError):
        get_article(db, 987654)


# --------------------------------------------------------------------- variants

def test_child_needs_a_parent(db):
    with pytest.raises(DomainError, match="braucht einen Elternartikel"):
        _article(db, kind=ArticleKind.CHILD.value)


def test_child_parent_must_actually_be_a_parent(db):
    standalone = _article(db)
    with pytest.raises(DomainError, match="kein Elternartikel"):
        _article(db, kind=ArticleKind.CHILD.value, parent_id=standalone.id)


def test_standalone_may_not_have_a_parent(db):
    parent = _article(db, kind=ArticleKind.PARENT.value)
    with pytest.raises(DomainError, match="Nur Artikel"):
        _article(db, kind=ArticleKind.STANDALONE.value, parent_id=parent.id)


def test_valid_variant_tree(db):
    parent = _article(db, kind=ArticleKind.PARENT.value, variant_axis="pin_count")
    child = _article(db, title="Gehäuse 4-polig", kind=ArticleKind.CHILD.value,
                     parent_id=parent.id)
    assert child.parent is parent
    assert parent.carries_stock is False
    assert child.carries_stock is True


def test_parent_with_children_cannot_be_demoted(db):
    parent = _article(db, kind=ArticleKind.PARENT.value)
    _article(db, title="Variante", kind=ArticleKind.CHILD.value, parent_id=parent.id)
    with pytest.raises(DomainError, match="Varianten"):
        update_article(db, parent, {"kind": ArticleKind.STANDALONE.value})


# ------------------------------------------------------------------- OE numbers

def test_oe_numbers_are_normalised_and_deduplicated(db):
    article = _article(db)
    set_oe_numbers(db, article, [("1J0 973 722", "VAG"), ("1j0-973.722", "VAG")])
    db.refresh(article)
    assert len(article.oe_numbers) == 1
    assert article.oe_numbers[0].oe_number.normalised == "1J0973722"
    assert article.oe_numbers[0].is_primary is True


def test_oe_number_rows_are_shared_between_articles(db):
    first = _article(db)
    second = _article(db, title="Reparatursatz")
    set_oe_numbers(db, first, [("1J0973722", "VAG")])
    set_oe_numbers(db, second, [("1J0 973 722", "VAG")])
    assert db.scalar(select(OeNumber).where(OeNumber.normalised == "1J0973722")) is not None
    assert len(db.scalars(select(OeNumber)).all()) == 1


def test_setting_oe_numbers_replaces_the_previous_set(db):
    article = _article(db)
    set_oe_numbers(db, article, [("A111", ""), ("B222", "")])
    set_oe_numbers(db, article, [("C333", "")])
    db.refresh(article)
    assert [link.oe_number.number for link in article.oe_numbers] == ["C333"]


def test_cross_references_are_deduplicated(db):
    article = _article(db)
    set_cross_references(db, article, [
        ("Herth+Buss", "51 27 0123", "passend"),
        ("Herth+Buss", "51270123", "doppelt"),
    ])
    db.refresh(article)
    assert len(article.cross_references) == 1


# ------------------------------------------------------------------ duplicates

def test_duplicate_found_by_mpn_regardless_of_formatting(db):
    existing = _article(db, mpn="MG 641 234")
    hits = find_duplicates(db, mpn="mg641234")
    assert [candidate.article.id for candidate in hits] == [existing.id]
    assert hits[0].reason == "Gleiche Herstellerteilenummer"


def test_duplicate_found_by_oe_number(db):
    existing = _article(db)
    set_oe_numbers(db, existing, [("1J0973722", "VAG")])
    hits = find_duplicates(db, oe_numbers=["1J0 973 722"])
    assert [candidate.article.id for candidate in hits] == [existing.id]
    assert hits[0].reason == "Gleiche OE-Nummer"


def test_duplicate_check_excludes_the_article_being_edited(db):
    article = _article(db, mpn="MG641234")
    assert find_duplicates(db, mpn="MG641234", exclude_article_id=article.id) == []


def test_no_duplicates_reported_for_a_fresh_part(db):
    _article(db, mpn="AAA111")
    assert find_duplicates(db, mpn="ZZZ999") == []


def test_normalise_part_number_handles_empty():
    assert normalise_part_number(None) == ""
    assert normalise_part_number("  ") == ""


# ---------------------------------------------------------------------- search

def test_search_finds_by_sku_title_and_mpn(db):
    article = _article(db, sku="CL-SUCHE-1", title="Steckergehäuse grau",
                       mpn="MG641234")
    for term in ("CL-SUCHE", "gehäuse", "MG641"):
        found, total = search_articles(db, term=term)
        assert article.id in [hit.id for hit in found], term
        assert total >= 1


def test_search_finds_by_oe_number_in_any_notation(db):
    article = _article(db, title="Über OE gefunden")
    set_oe_numbers(db, article, [("1J0973722", "VAG")])
    found, _ = search_articles(db, term="1J0 973 722")
    assert article.id in [hit.id for hit in found]


def test_search_excludes_inactive_by_default(db):
    article = _article(db, title="Ausgelaufener Artikel")
    deactivate_article(db, article)
    found, _ = search_articles(db, term="Ausgelaufener")
    assert found == []
    found, _ = search_articles(db, term="Ausgelaufener", only_active=False)
    assert [hit.id for hit in found] == [article.id]


def test_search_can_hide_variant_parents(db):
    parent = _article(db, title="Serie X Eltern", kind=ArticleKind.PARENT.value)
    found, _ = search_articles(db, term="Serie X", include_variant_parents=False)
    assert parent.id not in [hit.id for hit in found]


def test_search_paginates_with_an_honest_total(db):
    for index in range(7):
        _article(db, title=f"Paginierung {index}")
    page, total = search_articles(db, term="Paginierung", limit=3, offset=0)
    assert len(page) == 3
    assert total == 7


def test_search_filters_by_product_group(db):
    group = ProductGroup(code="TST", name="Testgruppe")
    db.add(group)
    db.flush()
    inside = _article(db, title="In der Gruppe", product_group_id=group.id)
    _article(db, title="Ohne Gruppe")
    found, total = search_articles(db, product_group_id=group.id)
    assert [hit.id for hit in found] == [inside.id]
    assert total == 1


# ---------------------------------------------------------------------- updates

def test_update_records_each_changed_field(db, admin_user):
    article = _article(db, sales_price_gross=Decimal("4.99"))
    changed = update_article(db, article,
                             {"title": "Neuer Titel",
                              "sales_price_gross": Decimal("5.99")},
                             user_id=admin_user.id)
    assert changed == 2
    db.flush()
    fields = {row.field_name for row in db.scalars(
        select(AuditLog).where(AuditLog.entity_id == article.id,
                               AuditLog.action == "update"))}
    assert fields == {"title", "sales_price_gross"}


def test_deactivate_keeps_the_row(db):
    article = _article(db)
    deactivate_article(db, article)
    assert article.is_active is False
    assert db.get(Article, article.id) is not None


def test_deactivate_is_idempotent(db):
    article = _article(db)
    deactivate_article(db, article)
    deactivate_article(db, article)
    db.flush()
    changes = db.scalars(
        select(AuditLog).where(AuditLog.entity_id == article.id,
                               AuditLog.field_name == "is_active")).all()
    assert len(changes) == 1


# ---------------------------------------------------------------------- margin

def test_margin_uses_average_cost_when_available(db):
    article = _article(db, sales_price_gross=Decimal("11.90"),
                       vat_rate=Decimal("19.00"),
                       purchase_price_net=Decimal("8.00"),
                       average_cost_net=Decimal("6.00"))
    # net price 10.00, cost 6.00 -> 40 %
    assert compute_margin(article) == Decimal("40.00")


def test_margin_falls_back_to_the_list_purchase_price(db):
    article = _article(db, sales_price_gross=Decimal("11.90"),
                       vat_rate=Decimal("19.00"),
                       purchase_price_net=Decimal("5.00"))
    assert compute_margin(article) == Decimal("50.00")


def test_margin_is_none_when_a_price_is_missing(db):
    assert compute_margin(_article(db)) is None
    assert compute_margin(_article(db, title="Nur EK",
                                   purchase_price_net=Decimal("5.00"))) is None


def test_manufacturer_relation(db):
    maker = Manufacturer(name="TE Connectivity")
    db.add(maker)
    db.flush()
    article = _article(db, manufacturer_id=maker.id)
    assert article.manufacturer.name == "TE Connectivity"
