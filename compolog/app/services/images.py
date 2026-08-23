"""Modul 1 -- Artikelbilder.

Files live on disk under settings.image_dir, the database holds only the relative
path. Rationale: a few thousand articles with several photos each is gigabytes of
JPEG, and a database is a poor filesystem -- backups get slow, and serving an
image means a round trip through the ORM.

The layout is <SKU>/<sha256-prefix>.<ext>. Naming by content hash means
re-uploading the same photo is idempotent, and it sidesteps every filename
sanitisation problem: the user's original name is kept in the database for
display, never used as a path.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import DomainError, NotFoundError
from app.logging_config import get_logger
from app.models.catalog import Article, ArticleImage

logger = get_logger("images")

# eBay accepts JPEG, PNG, GIF, BMP, TIFF. This list is the intersection with what
# is sensible to store and serve.
ALLOWED_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
MAX_IMAGE_BYTES = 12 * 1024 * 1024

# Magic bytes, checked because a Content-Type header is whatever the client says
# it is. Not a security boundary on its own, but it stops the obvious mistakes.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
]

# Dots are excluded deliberately: they are what turns a SKU into "..", and the
# file extension is appended separately anyway.
_SAFE_SKU = re.compile(r"[^A-Za-z0-9_-]")


def _sniff_content_type(data: bytes) -> str | None:
    for signature, content_type in _SIGNATURES:
        if data.startswith(signature):
            return content_type
    # WEBP: "RIFF" .... "WEBP"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _article_dir(article: Article) -> Path:
    """Directory for one article's images. The SKU is sanitised, never trusted."""
    safe = _SAFE_SKU.sub("_", article.sku) or f"id-{article.id}"
    return settings.image_dir / safe


def add_image(
    db: Session,
    article: Article,
    *,
    data: bytes,
    original_filename: str = "",
    alt_text: str = "",
) -> ArticleImage:
    """Store one image and attach it to the article."""
    if not data:
        raise DomainError("Die hochgeladene Datei ist leer.")
    if len(data) > MAX_IMAGE_BYTES:
        raise DomainError(
            f"Das Bild ist größer als {MAX_IMAGE_BYTES // (1024 * 1024)} MB."
        )

    content_type = _sniff_content_type(data)
    if content_type is None:
        raise DomainError(
            "Nicht unterstütztes Bildformat. Erlaubt sind JPEG, PNG, WEBP und GIF."
        )

    checksum = hashlib.sha256(data).hexdigest()
    existing = db.scalar(
        select(ArticleImage).where(ArticleImage.article_id == article.id,
                                   ArticleImage.checksum_sha256 == checksum)
    )
    if existing is not None:
        # Same bytes already attached -- silently keep the original rather than
        # creating a second identical eBay upload later.
        return existing

    directory = _article_dir(article)
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"{checksum[:16]}{ALLOWED_CONTENT_TYPES[content_type]}"
    (directory / filename).write_bytes(data)

    next_order = (db.scalar(
        select(func.max(ArticleImage.sort_order))
        .where(ArticleImage.article_id == article.id)
    ) or 0) + 1
    has_primary = db.scalar(
        select(func.count()).select_from(ArticleImage)
        .where(ArticleImage.article_id == article.id,
               ArticleImage.is_primary.is_(True))
    ) or 0

    image = ArticleImage(
        article_id=article.id,
        relative_path=f"{directory.name}/{filename}",
        original_filename=original_filename[:255],
        content_type=content_type,
        byte_size=len(data),
        checksum_sha256=checksum,
        sort_order=next_order,
        is_primary=has_primary == 0,   # first image becomes the main image
        alt_text=alt_text[:255],
    )
    db.add(image)
    db.flush()
    # The row was added directly rather than appended to article.images, so the
    # loaded collection is stale -- callers reading article.images straight after
    # an upload would not see the new photo.
    db.expire(article, ["images"])
    logger.info("image_added", extra={"article_id": article.id,
                                      "image_id": image.id, "bytes": len(data)})
    return image


def set_primary(db: Session, article: Article, image_id: int) -> None:
    """Exactly one main image per article."""
    target = None
    for image in article.images:
        image.is_primary = image.id == image_id
        if image.is_primary:
            target = image
    if target is None:
        raise NotFoundError("Bild gehört nicht zu diesem Artikel.")
    db.flush()


def reorder(db: Session, article: Article, ordered_ids: list[int]) -> None:
    """Apply a new display order. Ids not listed keep their relative position
    at the end, so a partial drag-and-drop payload cannot lose an image."""
    by_id = {image.id: image for image in article.images}
    position = 0
    for image_id in ordered_ids:
        image = by_id.pop(image_id, None)
        if image is not None:
            position += 1
            image.sort_order = position
    for image in by_id.values():
        position += 1
        image.sort_order = position
    db.flush()


def delete_image(db: Session, article: Article, image_id: int) -> None:
    """Remove an image, promoting another to main image if needed.

    The file on disk is removed too. It is deleted *after* the database row, and
    a failure to unlink is logged rather than raised: an orphaned file wastes a
    few kilobytes, while a failed transaction here would leave a dangling row.
    """
    image = next((candidate for candidate in article.images
                  if candidate.id == image_id), None)
    if image is None:
        raise NotFoundError("Bild gehört nicht zu diesem Artikel.")

    was_primary = image.is_primary
    path = settings.image_dir / image.relative_path
    db.delete(image)
    db.flush()
    db.refresh(article)

    if was_primary and article.images:
        article.images[0].is_primary = True
        db.flush()

    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("image_file_not_removed", extra={"path": str(path)})


def primary_image(article: Article) -> ArticleImage | None:
    for image in article.images:
        if image.is_primary:
            return image
    return article.images[0] if article.images else None
