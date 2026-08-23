"""The exact-decimal column type.

These tests exist because a float sneaking into a price column is the kind of bug
that shows up as a one-cent discrepancy in an invoice two years later.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.base import ExactDecimal, Money
from app.models.catalog import Article
from app.models.enums import ArticleKind


def test_round_trip_is_exact():
    column = Money()
    for value in ("0.01", "19.99", "1234.5678", "-45.60", "0"):
        stored = column.process_bind_param(Decimal(value), None)
        assert isinstance(stored, int)
        assert column.process_result_value(stored, None) == Decimal(value)


def test_float_is_rejected():
    with pytest.raises(TypeError, match="Float"):
        Money().process_bind_param(19.99, None)


def test_excess_precision_is_rejected():
    """Better a loud error than a silently truncated price."""
    with pytest.raises(ValueError, match="decimal places"):
        Money().process_bind_param(Decimal("1.234567"), None)


def test_scale_three_for_measures():
    column = ExactDecimal(scale=3)
    assert column.process_bind_param(Decimal("12.345"), None) == 12345
    assert column.process_result_value(12345, None) == Decimal("12.345")


def test_no_drift_over_many_additions(db):
    """The classic float failure: 0.1 added a hundred times."""
    article = Article(sku="CL-TEST-01", title="Testartikel",
                      kind=ArticleKind.STANDALONE.value,
                      sales_price_gross=Decimal("0.10"))
    db.add(article)
    db.flush()
    db.expire(article)

    total = sum((article.sales_price_gross for _ in range(100)), Decimal("0"))
    assert total == Decimal("10.00")


def test_price_survives_the_database(db):
    article = Article(sku="CL-TEST-02", title="Steckergehäuse 4-polig",
                      kind=ArticleKind.STANDALONE.value,
                      purchase_price_net=Decimal("1.2345"),
                      sales_price_gross=Decimal("4.99"),
                      vat_rate=Decimal("19.00"))
    db.add(article)
    db.flush()
    db.expire(article)

    loaded = db.scalar(select(Article).where(Article.sku == "CL-TEST-02"))
    assert loaded.purchase_price_net == Decimal("1.2345")
    assert loaded.sales_price_gross == Decimal("4.99")


def test_net_price_is_derived_from_gross(db):
    article = Article(sku="CL-TEST-03", title="Testartikel",
                      kind=ArticleKind.STANDALONE.value,
                      sales_price_gross=Decimal("11.90"),
                      vat_rate=Decimal("19.00"))
    # 11.90 / 1.19 = 10.00 exactly
    assert article.sales_price_net == Decimal("10.0000")
