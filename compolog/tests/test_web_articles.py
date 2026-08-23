"""Modul 1 -- Weboberfläche der Artikelverwaltung."""

from __future__ import annotations

import struct
import zlib

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models.auth import User
from app.models.enums import UserRole
from app.security import hash_password


def _png() -> bytes:
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _login(client, username: str, role: str = UserRole.ADMIN.value) -> None:
    """Log in, creating the user on first use.

    Unlike the `db` fixture, the TestClient talks to the real database through
    the app's own sessions, so nothing here is rolled back between tests. The
    user therefore has to be created only once.
    """
    password = "ein-gutes-passwort"
    with session_scope() as db:
        if db.scalar(select(User).where(User.username == username)) is None:
            db.add(User(username=username, full_name=username, role=role,
                        password_hash=hash_password(password)))
    response = client.post("/login",
                           data={"username": username, "password": password, "next": "/"},
                           follow_redirects=False)
    assert response.status_code == 303


@pytest.fixture
def admin_client(client):
    _login(client, "artikel-admin", UserRole.ADMIN.value)
    return client


def _create(client, **overrides) -> str:
    data = {"title": "Steckergehäuse 4-polig", "kind": "standalone",
            "condition": "new", "vat_rate": "19,00", "is_active": "1"}
    data.update(overrides)
    response = client.post("/artikel/neu", data=data, follow_redirects=False)
    assert response.status_code == 303, response.text[:500]
    return response.headers["location"]


def test_article_list_requires_login(client):
    assert client.get("/artikel", follow_redirects=False).status_code == 303


def test_empty_list_says_so(admin_client):
    response = admin_client.get("/artikel?q=gibtesnichtxyz")
    assert response.status_code == 200
    assert "Keine Artikel gefunden" in response.text


def test_create_and_view_an_article(admin_client):
    location = _create(admin_client, title="Steckergehäuse grün", mpn="MG641234")
    detail = admin_client.get(location)
    assert detail.status_code == 200
    assert "Steckergehäuse grün" in detail.text
    assert "MG641234" in detail.text


def test_created_article_appears_in_the_search(admin_client):
    _create(admin_client, title="Suchbarer Artikel")
    response = admin_client.get("/artikel?q=Suchbarer")
    assert "Suchbarer Artikel" in response.text


def test_title_over_80_characters_is_refused_with_a_german_message(admin_client):
    response = admin_client.post("/artikel/neu",
                                 data={"title": "x" * 81, "kind": "standalone",
                                       "condition": "new", "vat_rate": "19,00"},
                                 headers={"accept": "text/html"})
    assert response.status_code == 400
    assert "eBay erlaubt" in response.text
    assert "Traceback" not in response.text


def test_empty_title_is_refused(admin_client):
    response = admin_client.post("/artikel/neu",
                                 data={"title": "  ", "kind": "standalone",
                                       "condition": "new"},
                                 headers={"accept": "text/html"})
    assert response.status_code == 400
    assert "Titel darf nicht leer sein" in response.text


def test_duplicate_warning_is_shown_then_can_be_overridden(admin_client):
    _create(admin_client, title="Erster Artikel", mpn="MG999888")

    payload = {"title": "Vermeintliches Duplikat", "kind": "standalone",
               "condition": "new", "vat_rate": "19,00", "mpn": "mg 999 888"}
    warned = admin_client.post("/artikel/neu", data=payload)
    assert warned.status_code == 409
    assert "Doppelanlage" in warned.text
    assert "Erster Artikel" in warned.text

    # Confirming creates it anyway -- two parts can share a number.
    payload["ignore_duplicates"] = "1"
    confirmed = admin_client.post("/artikel/neu", data=payload, follow_redirects=False)
    assert confirmed.status_code == 303


def test_editing_records_history_and_shows_it(admin_client):
    location = _create(admin_client, title="Alter Titel")
    admin_client.post(f"{location}/bearbeiten",
                      data={"title": "Neuer Titel", "kind": "standalone",
                            "condition": "new", "vat_rate": "19,00", "is_active": "1"},
                      follow_redirects=False)
    detail = admin_client.get(location)
    assert "Neuer Titel" in detail.text
    assert "Änderungshistorie" in detail.text
    assert "Alter Titel" in detail.text, "alter Wert muss in der Historie stehen"


def test_oe_numbers_are_saved_from_the_form(admin_client):
    location = _create(admin_client, title="Artikel mit OE",
                       **{"oe_number_0": "1J0 973 722", "oe_brand_0": "VAG"})
    detail = admin_client.get(location)
    assert "1J0 973 722" in detail.text


def test_deactivate_hides_it_from_the_default_list(admin_client):
    location = _create(admin_client, title="Auslaufartikel")
    assert "Keine Artikel gefunden" not in admin_client.get(
        "/artikel?q=Auslaufartikel").text

    admin_client.post(f"{location}/deaktivieren", follow_redirects=False)

    # The search term is echoed in the export links, so assert on the result
    # state rather than on the word appearing anywhere in the page.
    hidden = admin_client.get("/artikel?q=Auslaufartikel")
    assert "Keine Artikel gefunden" in hidden.text

    shown = admin_client.get("/artikel?q=Auslaufartikel&inaktiv=true")
    assert "Keine Artikel gefunden" not in shown.text
    assert "(inaktiv)" in shown.text


def test_warehouse_user_may_look_but_not_change(client):
    _login(client, "lagerkraft", UserRole.WAREHOUSE.value)
    assert client.get("/artikel").status_code == 200
    response = client.post("/artikel/neu",
                           data={"title": "Verbotener Artikel", "kind": "standalone",
                                 "condition": "new"},
                           headers={"accept": "text/html"})
    assert response.status_code == 400
    assert "Administratoren" in response.text


def test_image_upload_and_delivery(admin_client):
    location = _create(admin_client, title="Bildartikel")
    upload = admin_client.post(f"{location}/bilder",
                               files={"bilder": ("front.png", _png(), "image/png")},
                               follow_redirects=False)
    assert upload.status_code == 303

    detail = admin_client.get(location)
    assert "/bilder/" in detail.text
    assert "Hauptbild" in detail.text

    # The image itself must be served, and only to a logged-in user.
    import re
    match = re.search(r"/artikel/\d+/bilder/(\d+)/datei", detail.text)
    assert match
    served = admin_client.get(match.group(0))
    assert served.status_code == 200
    assert served.content.startswith(b"\x89PNG")


def test_images_are_not_public(client, admin_client):
    location = _create(admin_client, title="Privates Bild")
    admin_client.post(f"{location}/bilder",
                      files={"bilder": ("front.png", _png(), "image/png")},
                      follow_redirects=False)
    detail = admin_client.get(location)
    import re
    path = re.search(r"/artikel/\d+/bilder/\d+/datei", detail.text).group(0)

    admin_client.post("/logout", follow_redirects=False)
    assert admin_client.get(path, follow_redirects=False).status_code == 303


def test_csv_export_downloads(admin_client):
    _create(admin_client, title="Export-Artikel")
    response = admin_client.get("/artikel/export?format=csv")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    assert "Export-Artikel" in response.content.decode("utf-8-sig")


def test_xlsx_export_downloads(admin_client):
    _create(admin_client, title="Excel-Artikel")
    response = admin_client.get("/artikel/export?format=xlsx")
    assert response.status_code == 200
    assert response.content[:2] == b"PK"


def test_import_dry_run_reports_without_saving(admin_client):
    payload = "Titel;VK brutto\r\nImportierter Artikel;4,99\r\n".encode("utf-8-sig")
    response = admin_client.post("/artikel/import",
                                 files={"datei": ("liste.csv", payload, "text/csv")})
    assert response.status_code == 200
    assert "Probelauf" in response.text
    assert "1 neu" in response.text
    # Nothing stored yet.
    assert "Importierter Artikel" not in admin_client.get(
        "/artikel?q=Importierter").text


def test_import_commit_creates_the_articles(admin_client):
    payload = "Titel;VK brutto\r\nÜbernommener Artikel;4,99\r\n".encode("utf-8-sig")
    response = admin_client.post(
        "/artikel/import",
        files={"datei": ("liste.csv", payload, "text/csv")},
        data={"uebernehmen": "1"},
    )
    assert response.status_code == 200
    assert "Import durchgeführt" in response.text
    assert "Übernommener Artikel" in admin_client.get("/artikel?q=Übernommener").text


def test_import_shows_bad_rows(admin_client):
    payload = ("Titel;VK brutto\r\nGuter;1,00\r\nKaputter;keine Zahl\r\n"
               ).encode("utf-8-sig")
    response = admin_client.post("/artikel/import",
                                 files={"datei": ("liste.csv", payload, "text/csv")})
    assert "Fehlerhafte Zeilen" in response.text
    assert "keine gültige Zahl" in response.text


def test_htmx_search_returns_only_the_table(admin_client):
    _create(admin_client, title="HTMX-Artikel")
    response = admin_client.get("/artikel?q=HTMX", headers={"hx-request": "true"})
    assert response.status_code == 200
    assert "HTMX-Artikel" in response.text
    assert "<html" not in response.text.lower()
