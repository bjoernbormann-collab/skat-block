"""Backups. A backup that has never been restored is a rumour, so at minimum the
suite proves the dump is a readable database."""

from __future__ import annotations

import sqlite3

from app.config import settings
from app.services.backup import dump_database, prune_old_backups, run_backup


def test_dump_produces_an_openable_database(db, tmp_path):
    stamp = "20260101-000000"
    dumped = dump_database(tmp_path, stamp)
    assert dumped.exists() and dumped.stat().st_size > 0

    # The real test: can it be opened and queried?
    connection = sqlite3.connect(dumped)
    tables = {row[0] for row in connection.execute(
        "select name from sqlite_master where type='table'")}
    connection.close()
    assert "articles" in tables
    assert "documents" in tables


def test_run_backup_writes_checksums(db):
    artefacts = run_backup()
    assert artefacts, "Backup hat nichts erzeugt"

    folders = sorted(p for p in settings.backup_dir.iterdir() if p.is_dir())
    checksums = folders[-1] / "SHA256SUMS"
    assert checksums.exists()

    content = checksums.read_text(encoding="utf-8")
    for name, digest in artefacts.items():
        assert f"{digest}  {name}" in content


def test_prune_keeps_recent_and_removes_old(db):
    run_backup()
    old = settings.backup_dir / "20200101-000000"
    old.mkdir(parents=True, exist_ok=True)
    (old / "compolog-20200101-000000.db").write_bytes(b"alt")

    assert prune_old_backups(keep_days=30) >= 1
    assert not old.exists()


def test_prune_ignores_foreign_directories(db):
    stranger = settings.backup_dir / "time-machine"
    stranger.mkdir(parents=True, exist_ok=True)
    prune_old_backups(keep_days=0)
    assert stranger.exists(), "fremde Verzeichnisse dürfen nicht gelöscht werden"
