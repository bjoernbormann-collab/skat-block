"""Automated backups (Querschnittsanforderung).

Three things have to survive a disk failure, and losing any one of them is a
different kind of bad:

* the database  -- the whole business
* the documents -- invoices are subject to a ten-year retention duty (§147 AO)
* the images    -- annoying to lose, expensive to re-photograph

The database is copied with SQLite's own backup API rather than by copying the
file. A plain file copy of a database in WAL mode while the app is running can
produce a torn, unopenable snapshot -- and you would only find out on the day you
need it.

NOT INCLUDED ON PURPOSE: the .env. It holds the key that decrypts the eBay
tokens, so it must not travel with a backup that leaves the house. Keep it in a
password manager instead.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tarfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("backup")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_database(target_dir: Path, stamp: str) -> Path:
    """Consistent snapshot of the database."""
    target_dir.mkdir(parents=True, exist_ok=True)

    if not settings.is_sqlite:
        # PostgreSQL: pg_dump is the right tool, but shelling out needs the
        # credentials and the binary, so it is left explicit rather than guessed.
        raise NotImplementedError(
            "Für PostgreSQL bitte pg_dump einbinden – siehe README, Abschnitt "
            "Backup. (Bewusst nicht implementiert, nicht vergessen.)"
        )

    source = settings.database_url.replace("sqlite:///", "")
    destination = target_dir / f"compolog-{stamp}.db"
    # sqlite3's online backup API: safe against concurrent writers, unlike cp.
    with sqlite3.connect(source) as src, sqlite3.connect(destination) as dst:
        src.backup(dst)
    logger.info("database_backup_written",
                extra={"path": str(destination), "bytes": destination.stat().st_size})
    return destination


def archive_directory(source: Path, target_dir: Path, name: str, stamp: str) -> Path | None:
    """tar.gz one data directory. Returns None if there is nothing to archive."""
    if not source.exists() or not any(source.iterdir()):
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / f"{name}-{stamp}.tar.gz"
    with tarfile.open(destination, "w:gz") as tar:
        tar.add(source, arcname=name)
    return destination


def run_backup() -> dict[str, str]:
    """Full backup run. Returns {artefact: sha256} for logging and verification."""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = settings.backup_dir / stamp
    target.mkdir(parents=True, exist_ok=True)

    artefacts: dict[str, str] = {}
    db_file = dump_database(target, stamp)
    artefacts[db_file.name] = _sha256(db_file)

    for name, source in (("documents", settings.document_dir),
                         ("images", settings.image_dir)):
        archive = archive_directory(source, target, name, stamp)
        if archive is not None:
            artefacts[archive.name] = _sha256(archive)

    # Checksums travel with the backup so its integrity can be checked without
    # this application being available.
    (target / "SHA256SUMS").write_text(
        "\n".join(f"{digest}  {name}" for name, digest in sorted(artefacts.items())) + "\n",
        encoding="utf-8",
    )
    logger.info("backup_completed", extra={"target": str(target),
                                           "artefacts": list(artefacts)})
    prune_old_backups()
    return artefacts


def prune_old_backups(keep_days: int | None = None) -> int:
    """Delete backup folders older than the retention window. Returns the count.

    Note: this only prunes *this* directory. If it is synced to an external disk
    or Time Machine, the retention there is a separate decision -- and for
    invoices the legal retention is ten years, far longer than this window.
    """
    keep = keep_days if keep_days is not None else settings.backup_keep_days
    cutoff = datetime.now(UTC) - timedelta(days=keep)
    removed = 0
    for entry in settings.backup_dir.iterdir():
        if not entry.is_dir():
            continue
        try:
            created = datetime.strptime(entry.name, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            continue  # not one of ours -- leave it alone
        if created < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    if removed:
        logger.info("backups_pruned", extra={"removed": removed, "keep_days": keep})
    return removed
