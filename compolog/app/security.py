"""Password hashing and server-side sessions."""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.auth import LoginSession, User
from app.models.base import utcnow

# bcrypt directly, not via passlib: passlib has been unmaintained since 2020 and
# its bcrypt backend breaks against bcrypt >= 4.1. The API used here is three
# functions wide, so the wrapper bought us nothing.
#
# 12 rounds is roughly 250 ms on an M-series Mac -- deliberate, and irrelevant at
# a handful of logins a day.
BCRYPT_ROUNDS = 12
BCRYPT_MAX_BYTES = 72  # hard limit of the algorithm; anything beyond is ignored

# Hash of a value nobody can log in with, used to spend the same time on an
# unknown username as on a wrong password.
_DUMMY_HASH = bcrypt.hashpw(b"dummy-password-for-timing", bcrypt.gensalt(rounds=BCRYPT_ROUNDS))

MAX_FAILED_LOGINS = 8
LOCKOUT = timedelta(minutes=15)


def hash_password(plain: str) -> str:
    encoded = plain.encode("utf-8")
    # bcrypt truncates silently at 72 bytes. Refusing is better than accepting a
    # password whose tail turns out not to matter.
    if len(encoded) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"Passwort darf höchstens {BCRYPT_MAX_BYTES} Bytes lang sein "
            "(Umlaute zählen doppelt)."
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    encoded = plain.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, hashed.encode("ascii"))
    except (ValueError, TypeError):
        # Malformed hash in the database -- treat as a failed login, not a crash.
        return False


def _dummy_verify() -> None:
    """Burn the same CPU time as a real check, to hide whether a user exists."""
    bcrypt.checkpw(b"dummy-password-for-timing", _DUMMY_HASH)


def authenticate(db: Session, username: str, password: str) -> User | None:
    """Return the user on success, None otherwise.

    Runs a dummy hash comparison for unknown users so that "user does not exist"
    and "wrong password" take the same amount of time.
    """
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        _dummy_verify()
        return None
    if not user.is_active:
        return None
    if user.locked_until and user.locked_until > utcnow():
        return None

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = utcnow() + LOCKOUT
            user.failed_login_count = 0
        db.flush()
        return None

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    db.flush()
    return user


def create_session(db: Session, user: User, *, user_agent: str = "",
                   ip_address: str = "") -> LoginSession:
    session_row = LoginSession(
        token=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=utcnow() + timedelta(seconds=settings.session_max_age_seconds),
        user_agent=user_agent[:255],
        ip_address=ip_address[:64],
    )
    db.add(session_row)
    db.flush()
    return session_row


def resolve_session(db: Session, token: str | None) -> User | None:
    """Look up the user behind a session cookie, or None if it is not usable."""
    if not token:
        return None
    row = db.scalar(select(LoginSession).where(LoginSession.token == token))
    if row is None:
        return None
    # Constant-time compare even though the lookup already matched -- cheap, and
    # keeps the comparison honest if the lookup ever becomes a prefix search.
    if not hmac.compare_digest(row.token, token):
        return None
    if row.revoked_at is not None or row.expires_at <= utcnow():
        return None
    user = row.user
    return user if user and user.is_active else None


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return
    row = db.scalar(select(LoginSession).where(LoginSession.token == token))
    if row is not None and row.revoked_at is None:
        row.revoked_at = utcnow()
        db.flush()


def purge_expired_sessions(db: Session) -> int:
    """Housekeeping for the nightly job."""
    rows = db.scalars(
        select(LoginSession).where(LoginSession.expires_at <= utcnow())
    ).all()
    for row in rows:
        db.delete(row)
    return len(rows)
