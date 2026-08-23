"""Modul 1 -- Import und Export."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models.catalog import Article, Manufacturer, ProductGroup, Supplier
from app.services.importexport import (
    ParseError,
    export_csv,
    export_xlsx,
    import_articles,
    parse_bool,
    parse_condition,
    parse_decimal,
    read_table,
    suggest_mapping,
)

# ---------------------------------------------------------------------- parsing

@pytest.mark.parametrize(("raw", "expected"), [
    ("1234.56", Decimal("1234.56")),
    ("1.234,56", Decimal("1234.56")),
    ("1,234.56", Decimal("1234.56")),
    ("4,99", Decimal("4.99")),
    ("4,99 €", Decimal("4.99")),
    ("  12 ", Decimal("12")),
    ("", None),
])
def test_decimal_parsing_handles_german_and_english_notation(raw, expected):
    assert parse_decimal(raw) == expected


def test_decimal_parsing_refuses_nonsense():
    with pytest.raises(ParseError, match="keine gültige Zahl"):
        parse_decimal("ca. fünf Euro")


def test_bool_parsing():
    assert parse_bool("ja") is True
    assert parse_bool("nein") is False
    assert parse_bool("") is None
    with pytest.raises(ParseError):
        parse_bool("vielleicht")


def test_condition_parsing():
    assert parse_condition("Neu") == "new"
    assert parse_condition("generalüberholt") == "refurbished"
    with pytest.raises(ParseError):
        parse_condition("bastlerqualität")


# ---------------------------------------------------------------------- reading

def _csv(rows: list[str]) -> bytes:
    return "\r\n".join(rows).encode("utf-8-sig")


def test_csv_is_read_with_semicolons_and_umlauts():
    data = _csv(["Artikelnummer;Titel;VK brutto",
                 "CL-1;Steckergehäuse grün;4,99"])
    headers, rows = read_table(data, "liste.csv")
    assert headers == ["Artikelnummer", "Titel", "VK brutto"]
    assert rows == [["CL-1", "Steckergehäuse grün", "4,99"]]


def test_csv_with_commas_is_also_read():
    data = _csv(["Artikelnummer,Titel", "CL-1,Testartikel"])
    headers, rows = read_table(data, "liste.csv")
    assert headers == ["Artikelnummer", "Titel"]
    assert rows == [["CL-1", "Testartikel"]]


def test_mapping_is_suggested_from_common_headers():
    mapping = suggest_mapping(["Artikelnr", "Titel", "EK netto", "Unbekannt"])
    assert mapping["Artikelnr"] == "sku"
    assert mapping["Titel"] == "title"
    assert mapping["EK netto"] == "purchase_price_net"
    assert "Unbekannt" not in mapping


# ---------------------------------------------------------------------- import

def _run(db, csv_rows: list[str], **kwargs):
    headers, rows = read_table(_csv(csv_rows), "liste.csv")
    mapping = kwargs.pop("mapping", None) or suggest_mapping(headers)
    return import_articles(db, headers=headers, rows=rows, mapping=mapping, **kwargs)


def test_dry_run_changes_nothing(db):
    report = _run(db, ["Titel;VK brutto", "Neuer Artikel;4,99"])
    assert report.created == 1
    assert report.dry_run is True
    assert db.scalar(select(Article).where(Article.title == "Neuer Artikel")) is None


def test_real_run_creates_articles(db):
    report = _run(db, ["Titel;VK brutto", "Neuer Artikel;4,99"], dry_run=False)
    assert report.created == 1
    article = db.scalar(select(Article).where(Article.title == "Neuer Artikel"))
    assert article is not None
    assert article.sales_price_gross == Decimal("4.99")
    assert article.sku.startswith("CL-")


def test_existing_article_is_updated_by_sku(db):
    _run(db, ["Artikelnummer;Titel;VK brutto", "CL-IMP-1;Alter Titel;1,00"],
         dry_run=False)
    report = _run(db, ["Artikelnummer;Titel;VK brutto", "CL-IMP-1;Neuer Titel;2,00"],
                  dry_run=False)
    assert report.updated == 1
    article = db.scalar(select(Article).where(Article.sku == "CL-IMP-1"))
    assert article.title == "Neuer Titel"
    assert article.sales_price_gross == Decimal("2.00")


def test_update_can_be_switched_off(db):
    _run(db, ["Artikelnummer;Titel", "CL-IMP-2;Original"], dry_run=False)
    report = _run(db, ["Artikelnummer;Titel", "CL-IMP-2;Überschrieben"],
                  dry_run=False, update_existing=False)
    assert report.skipped == 1
    assert db.scalar(
        select(Article).where(Article.sku == "CL-IMP-2")).title == "Original"


def test_a_bad_row_does_not_stop_the_others(db):
    report = _run(db, [
        "Titel;VK brutto",
        "Guter Artikel;4,99",
        "Kaputter Artikel;ungefähr fünf",
        "Noch ein guter;9,99",
    ])
    assert len(report.errors) == 1
    assert report.errors[0].row_number == 3
    assert report.created == 2


def test_nothing_is_committed_when_any_row_failed(db):
    report = _run(db, [
        "Titel;VK brutto",
        "Guter Artikel;4,99",
        "Kaputter Artikel;ungefähr fünf",
    ], dry_run=False)
    assert not report.ok
    assert db.scalar(select(Article).where(Article.title == "Guter Artikel")) is None


def test_missing_required_column_is_refused(db):
    with pytest.raises(ParseError, match="Pflichtspalten"):
        _run(db, ["Artikelnummer", "CL-1"], mapping={"Artikelnummer": "sku"})


def test_manufacturers_and_suppliers_are_created_on_the_fly(db):
    _run(db, ["Titel;Hersteller;Lieferant", "Testartikel;TE Connectivity;Muster GmbH"],
         dry_run=False)
    assert db.scalar(select(Manufacturer).where(Manufacturer.name == "TE Connectivity"))
    assert db.scalar(select(Supplier).where(Supplier.name == "Muster GmbH"))


def test_unknown_product_group_is_an_error_not_a_new_group(db):
    """A group carries the eBay category; inventing one from a typo would create
    articles that look fine and cannot be published."""
    report = _run(db, ["Titel;Warengruppe", "Testartikel;TIPPFEHLER"])
    assert len(report.errors) == 1
    assert "existiert nicht" in report.errors[0].message
    assert db.scalar(select(ProductGroup).where(ProductGroup.code == "TIPPFEHLER")) is None


def test_known_product_group_is_linked(db):
    db.add(ProductGroup(code="STV", name="Steckverbinder"))
    db.flush()
    _run(db, ["Titel;Warengruppe", "Testartikel;STV"], dry_run=False)
    article = db.scalar(select(Article).where(Article.title == "Testartikel"))
    assert article.product_group.code == "STV"


def test_oe_numbers_are_imported_from_a_quoted_list_cell(db):
    """A semicolon list inside a semicolon-delimited CSV -- has to be quoted, and
    the reader has to honour the quotes."""
    _run(db, ['Titel;OE-Nummern', 'Testartikel;"1J0973722; 4B0973712"'],
         dry_run=False)
    article = db.scalar(select(Article).where(Article.title == "Testartikel"))
    assert {link.oe_number.normalised for link in article.oe_numbers} == {
        "1J0973722", "4B0973712"}


def test_oe_numbers_are_imported_from_a_pipe_list(db):
    _run(db, ["Titel;OE-Nummern", "Pipe-Artikel;1J0973722|4B0973712"], dry_run=False)
    article = db.scalar(select(Article).where(Article.title == "Pipe-Artikel"))
    assert len(article.oe_numbers) == 2


def test_empty_rows_are_skipped(db):
    report = _run(db, ["Titel;VK brutto", "Echter Artikel;1,00", ";"])
    assert report.created == 1
    assert report.skipped == 0   # blank line is dropped while reading


# ---------------------------------------------------------------------- export

def test_csv_export_round_trips_back_into_the_importer(db):
    _run(db, ["Artikelnummer;Titel;VK brutto;Herstellerteilenummer",
              "CL-RT-1;Rundlauf-Artikel;7,50;MG641234"], dry_run=False)
    articles = list(db.scalars(select(Article).where(Article.sku == "CL-RT-1")))

    payload = export_csv(db, articles)
    assert payload.startswith(b"\xef\xbb\xbf"), "Excel braucht das BOM"

    headers, rows = read_table(payload, "export.csv")
    mapping = suggest_mapping(headers)
    # Every exported column must be recognised again -- otherwise "exportieren,
    # in Excel ändern, reimportieren" quietly loses data.
    assert set(mapping.values()) >= {"sku", "title", "sales_price_gross", "mpn"}
    assert rows[0][headers.index("Artikelnummer")] == "CL-RT-1"


def test_xlsx_export_is_readable_again(db):
    _run(db, ["Artikelnummer;Titel", "CL-XL-1;Excel-Artikel"], dry_run=False)
    articles = list(db.scalars(select(Article).where(Article.sku == "CL-XL-1")))

    payload = export_xlsx(db, articles)
    assert payload[:2] == b"PK"     # xlsx is a zip

    headers, rows = read_table(payload, "export.xlsx")
    assert "Titel" in headers
    assert rows[0][headers.index("Titel")] == "Excel-Artikel"


def test_export_writes_the_german_condition_and_reimports(db):
    _run(db, ["Artikelnummer;Titel;Zustand", "CL-ZU-1;Gebrauchtteil;gebraucht"],
         dry_run=False)
    articles = list(db.scalars(select(Article).where(Article.sku == "CL-ZU-1")))
    text = export_csv(db, articles).decode("utf-8-sig")
    assert "gebraucht" in text and "used" not in text

    headers, rows = read_table(export_csv(db, articles), "export.csv")
    report = import_articles(db, headers=headers, rows=rows,
                             mapping=suggest_mapping(headers), dry_run=False)
    assert report.ok
    assert db.scalar(
        select(Article).where(Article.sku == "CL-ZU-1")).condition == "used"


def test_export_writes_german_decimals(db):
    _run(db, ["Artikelnummer;Titel;VK brutto", "CL-DE-1;Preisartikel;1234,56"],
         dry_run=False)
    articles = list(db.scalars(select(Article).where(Article.sku == "CL-DE-1")))
    text = export_csv(db, articles).decode("utf-8-sig")
    assert "1234,56" in text
