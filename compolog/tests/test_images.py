"""Modul 1 -- Artikelbilder."""

from __future__ import annotations

import struct
import zlib

import pytest

from app.config import settings
from app.errors import DomainError, NotFoundError
from app.models.enums import ArticleKind
from app.services.articles import create_article
from app.services.images import (
    MAX_IMAGE_BYTES,
    add_image,
    delete_image,
    primary_image,
    reorder,
    set_primary,
)


def _png(width: int = 1, height: int = 1) -> bytes:
    """Smallest valid PNG, built by hand so the tests need no image library."""
    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _jpeg() -> bytes:
    return b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"


@pytest.fixture
def article(db):
    return create_article(db, {"title": "Bildartikel",
                               "kind": ArticleKind.STANDALONE.value})


def test_first_image_becomes_the_main_image(db, article):
    image = add_image(db, article, data=_png(), original_filename="front.png")
    assert image.is_primary is True
    assert image.sort_order == 1
    assert (settings.image_dir / image.relative_path).is_file()


def test_second_image_does_not_steal_the_main_flag(db, article):
    first = add_image(db, article, data=_png(2, 2))
    second = add_image(db, article, data=_jpeg())
    assert first.is_primary is True
    assert second.is_primary is False
    assert second.sort_order == 2


def test_same_bytes_are_not_stored_twice(db, article):
    """Re-uploading the same photo must not create a second eBay upload later."""
    data = _png(3, 3)
    first = add_image(db, article, data=data)
    second = add_image(db, article, data=data, original_filename="kopie.png")
    assert first.id == second.id
    db.refresh(article)
    assert len(article.images) == 1


def test_content_type_comes_from_the_bytes_not_the_filename(db, article):
    image = add_image(db, article, data=_jpeg(), original_filename="luege.png")
    assert image.content_type == "image/jpeg"
    assert image.relative_path.endswith(".jpg")


def test_non_image_is_refused(db, article):
    with pytest.raises(DomainError, match="Bildformat"):
        add_image(db, article, data=b"Das ist nur Text.", original_filename="a.png")


def test_empty_upload_is_refused(db, article):
    with pytest.raises(DomainError, match="leer"):
        add_image(db, article, data=b"")


def test_oversized_image_is_refused(db, article):
    payload = _png() + b"\x00" * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(DomainError, match="größer als"):
        add_image(db, article, data=payload)


def test_filename_cannot_escape_the_image_directory(db):
    """The SKU ends up in the path, so it has to be sanitised."""
    article = create_article(db, {"sku": "../../etc/passwd", "title": "Böse"})
    image = add_image(db, article, data=_png())
    stored = (settings.image_dir / image.relative_path).resolve()
    assert stored.is_relative_to(settings.image_dir.resolve())
    # Exactly one separator: "<sanitised-sku>/<hash>.png", nothing climbing out.
    assert image.relative_path.count("/") == 1
    assert ".." not in image.relative_path


def test_set_primary_moves_the_flag(db, article):
    first = add_image(db, article, data=_png(4, 4))
    second = add_image(db, article, data=_jpeg())
    set_primary(db, article, second.id)
    assert first.is_primary is False
    assert second.is_primary is True
    assert primary_image(article).id == second.id


def test_set_primary_rejects_a_foreign_image(db, article):
    other = create_article(db, {"title": "Anderer Artikel"})
    foreign = add_image(db, other, data=_png(5, 5))
    with pytest.raises(NotFoundError):
        set_primary(db, article, foreign.id)


def test_reorder_applies_the_new_sequence(db, article):
    first = add_image(db, article, data=_png(6, 6))
    second = add_image(db, article, data=_jpeg())
    reorder(db, article, [second.id, first.id])
    assert second.sort_order == 1
    assert first.sort_order == 2


def test_reorder_keeps_unlisted_images(db, article):
    first = add_image(db, article, data=_png(7, 7))
    second = add_image(db, article, data=_jpeg())
    reorder(db, article, [second.id])          # partial payload
    assert second.sort_order == 1
    assert first.sort_order == 2               # not lost


def test_deleting_the_main_image_promotes_another(db, article):
    first = add_image(db, article, data=_png(8, 8))
    second = add_image(db, article, data=_jpeg())
    delete_image(db, article, first.id)
    db.refresh(article)
    assert len(article.images) == 1
    assert article.images[0].id == second.id
    assert article.images[0].is_primary is True


def test_deleting_removes_the_file(db, article):
    image = add_image(db, article, data=_png(9, 9))
    path = settings.image_dir / image.relative_path
    delete_image(db, article, image.id)
    assert not path.exists()


def test_primary_image_falls_back_to_the_first(db, article):
    assert primary_image(article) is None
    image = add_image(db, article, data=_png(10, 10))
    image.is_primary = False
    db.flush()
    assert primary_image(article).id == image.id
