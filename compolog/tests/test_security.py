"""Password hashing, session handling and the login lockout."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models.base import utcnow
from app.security import (
    MAX_FAILED_LOGINS,
    authenticate,
    create_session,
    hash_password,
    purge_expired_sessions,
    resolve_session,
    revoke_session,
    verify_password,
)


def test_hash_is_salted():
    """Two hashes of the same password must differ, or the database leaks which
    users share a password."""
    assert hash_password("gleiches-passwort") != hash_password("gleiches-passwort")


def test_verify_accepts_correct_and_rejects_wrong():
    hashed = hash_password("richtiges-passwort")
    assert verify_password("richtiges-passwort", hashed)
    assert not verify_password("falsches-passwort", hashed)


def test_overlong_password_is_refused():
    with pytest.raises(ValueError, match="72 Bytes"):
        hash_password("x" * 73)


def test_umlauts_count_as_two_bytes():
    """bcrypt's limit is bytes, not characters -- 40 umlauts are 80 bytes."""
    with pytest.raises(ValueError):
        hash_password("ä" * 40)


def test_malformed_hash_does_not_crash():
    assert not verify_password("egal", "kein-gueltiger-bcrypt-hash")


def test_authenticate_succeeds(db, admin_user):
    assert authenticate(db, "test-admin", "test-passwort-1") is admin_user


def test_authenticate_fails_for_wrong_password(db, admin_user):
    assert authenticate(db, "test-admin", "falsch") is None


def test_authenticate_fails_for_unknown_user(db):
    assert authenticate(db, "gibt-es-nicht", "egal") is None


def test_inactive_user_cannot_log_in(db, admin_user):
    admin_user.is_active = False
    db.flush()
    assert authenticate(db, "test-admin", "test-passwort-1") is None


def test_account_locks_after_repeated_failures(db, admin_user):
    for _ in range(MAX_FAILED_LOGINS):
        assert authenticate(db, "test-admin", "falsch") is None
    assert admin_user.locked_until is not None
    # Even the correct password is refused while the lock holds.
    assert authenticate(db, "test-admin", "test-passwort-1") is None


def test_successful_login_clears_the_failure_counter(db, admin_user):
    authenticate(db, "test-admin", "falsch")
    assert admin_user.failed_login_count == 1
    authenticate(db, "test-admin", "test-passwort-1")
    assert admin_user.failed_login_count == 0
    assert admin_user.last_login_at is not None


def test_session_round_trip(db, admin_user):
    session_row = create_session(db, admin_user, user_agent="pytest", ip_address="127.0.0.1")
    assert resolve_session(db, session_row.token) is admin_user


def test_unknown_token_resolves_to_nobody(db):
    assert resolve_session(db, "gibt-es-nicht") is None
    assert resolve_session(db, None) is None


def test_expired_session_is_rejected(db, admin_user):
    session_row = create_session(db, admin_user)
    session_row.expires_at = utcnow() - timedelta(seconds=1)
    db.flush()
    assert resolve_session(db, session_row.token) is None


def test_revoked_session_is_rejected(db, admin_user):
    session_row = create_session(db, admin_user)
    revoke_session(db, session_row.token)
    assert resolve_session(db, session_row.token) is None


def test_deactivating_a_user_kills_their_sessions(db, admin_user):
    session_row = create_session(db, admin_user)
    admin_user.is_active = False
    db.flush()
    assert resolve_session(db, session_row.token) is None


def test_purge_removes_only_expired_sessions(db, admin_user, warehouse_user):
    live = create_session(db, admin_user)
    stale = create_session(db, warehouse_user)
    stale.expires_at = utcnow() - timedelta(days=1)
    db.flush()

    assert purge_expired_sessions(db) == 1
    assert resolve_session(db, live.token) is admin_user
