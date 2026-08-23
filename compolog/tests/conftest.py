"""Test fixtures.

Every test runs against a fresh SQLite file created by *the Alembic migrations*,
not by ``Base.metadata.create_all``. That is deliberate: it means the test suite
fails if a migration is missing or wrong, which is the failure mode that actually
hurts in production.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# This block runs at import time, BEFORE any test module -- and therefore before
# anything imports app.config, which reads the environment once and caches it.
# Setting DATABASE_URL in a fixture would be too late: the settings singleton
# would already point at the real database, and the suite would happily run
# against production data.
# ---------------------------------------------------------------------------
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="compolog-tests-"))

os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT / 'test.db'}"
os.environ["DATA_DIR"] = str(_TEST_ROOT)
os.environ["IMAGE_DIR"] = str(_TEST_ROOT / "images")
os.environ["DOCUMENT_DIR"] = str(_TEST_ROOT / "documents")
os.environ["BACKUP_DIR"] = str(_TEST_ROOT / "backups")
os.environ["LOG_DIR"] = str(_TEST_ROOT / "logs")
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["BACKUP_ENABLED"] = "false"
os.environ["SECRET_KEY"] = "test-secret-key-not-used-in-production"
os.environ["LOG_JSON"] = "false"
os.environ["DEBUG"] = "false"
os.environ["EBAY_SANDBOX"] = "true"


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """Run `alembic upgrade head` once for the whole session.

    Building the schema from the migrations rather than Base.metadata.create_all
    means a missing or broken migration fails the suite -- which is exactly the
    bug that otherwise only shows up on the production machine.
    """
    from alembic.config import Config

    from alembic import command
    from app.config import settings

    # Guard against the block above ever being bypassed.
    assert str(_TEST_ROOT) in settings.database_url, (
        "Tests laufen gegen die falsche Datenbank – conftest-Import-Reihenfolge prüfen."
    )
    settings.ensure_directories()

    root = Path(__file__).resolve().parent.parent
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
    try:
        yield
    finally:
        shutil.rmtree(_TEST_ROOT, ignore_errors=True)


@pytest.fixture
def db(migrated_database: None) -> Iterator:
    """A session whose transaction is rolled back after every test.

    The outer transaction is never committed, so tests cannot leak state into
    each other even though they share one database file.
    """
    from sqlalchemy.orm import Session

    from app.db import engine

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False,
                      join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def admin_user(db):
    from app.models.auth import User
    from app.models.enums import UserRole
    from app.security import hash_password

    user = User(username="test-admin", full_name="Test Admin",
                role=UserRole.ADMIN.value, password_hash=hash_password("test-passwort-1"))
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def warehouse_user(db):
    from app.models.auth import User
    from app.models.enums import UserRole
    from app.security import hash_password

    user = User(username="test-lager", full_name="Test Lager",
                role=UserRole.WAREHOUSE.value,
                password_hash=hash_password("test-passwort-2"))
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def client(migrated_database: None) -> Iterator:
    """TestClient with a real database (no session override).

    Used for the auth flow, where the point is that cookies and the session table
    work together.
    """
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client
