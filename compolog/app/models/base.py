"""Declarative base, shared column types and mixins.

Two decisions in here shape everything else, so they are documented at length:

1. Money and other exact decimals are stored as *scaled integers*, not as floats
   and not as SQL NUMERIC. SQLite has no native decimal type -- SQLAlchemy's
   Numeric() round-trips through a C double there, which is exactly the kind of
   silent cent-drift you do not want in an invoice. Storing 12.34 EUR as the
   integer 123400 (scale 4) is exact, sorts correctly, and SUM()/AVG() still work
   in plain SQL. It also behaves identically on SQLite and PostgreSQL, so the
   migration path stays a URL change instead of a data conversion.

2. Every timestamp is timezone-aware UTC. Rendering in Europe/Berlin happens in
   the templates only. eBay hands out UTC, DATEV wants local dates -- keeping one
   canonical representation in the database avoids an entire class of bugs.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    TypeDecorator,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Stable, explicit constraint names. Without a naming convention SQLite produces
# anonymous constraints that a later Alembic migration cannot drop by name --
# and on SQLite every ALTER is a table rebuild, so the names really do matter.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ExactDecimal(TypeDecorator):
    """Store a Decimal exactly as a scaled integer.

    ``scale=4`` means four decimal places: Decimal("19.99") -> 199900.
    Values are quantised on the way in, so a price of 1/3 EUR is rejected as a
    rounding decision rather than silently truncated.
    """

    impl = BigInteger
    cache_ok = True

    def __init__(self, scale: int = 4, **kwargs: Any) -> None:
        self.scale = scale
        self._factor = 10**scale
        self._quantum = Decimal(1).scaleb(-scale)
        super().__init__(**kwargs)

    def process_bind_param(self, value: Decimal | int | float | str | None, dialect):
        if value is None:
            return None
        if isinstance(value, float):
            # Refuse floats outright: 0.1 + 0.2 has no business near an invoice.
            raise TypeError(
                "Float assigned to an exact decimal column. Use Decimal('…') "
                "or a string instead."
            )
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
        quantised = dec.quantize(self._quantum)
        if quantised != dec:
            raise ValueError(
                f"Value {dec} needs more than {self.scale} decimal places; "
                "round it explicitly before storing."
            )
        return int(quantised * self._factor)

    def process_result_value(self, value: int | None, dialect):
        if value is None:
            return None
        return (Decimal(value) / self._factor).quantize(self._quantum)


def Money(**kwargs: Any) -> ExactDecimal:
    """EUR amount with four decimal places (net line prices need more than two)."""
    return ExactDecimal(scale=4, **kwargs)


def Percent(**kwargs: Any) -> ExactDecimal:
    """Percentage, e.g. Decimal('19.00') for a 19 % VAT rate."""
    return ExactDecimal(scale=4, **kwargs)


def Measure(**kwargs: Any) -> ExactDecimal:
    """Physical measure: grams, millimetres, decimals of an ampere."""
    return ExactDecimal(scale=3, **kwargs)


def Quantity(**kwargs: Any) -> ExactDecimal:
    """Stock quantity, three decimal places.

    Connectors are counted in whole pieces, so an integer column would do today.
    Decimal is used anyway because cut goods (Kabel, Schrumpfschlauch, Litze) are
    expected later, and widening quantities afterwards means migrating the stock
    journal, the reservations, every order and every issued document at once --
    on live data, with a paper trail that must stay consistent.

    Three decimals covers metres and grammes; more precision than that has no
    meaning in a parts warehouse.

    NOTE: this does NOT apply to the eBay mirror columns. eBay's Inventory API
    takes an integer quantity, so ebay_listings keeps Integer and the client
    rounds down at the boundary -- offering 2.7 m as 3 would oversell.
    """
    return ExactDecimal(scale=3, **kwargs)


class UtcDateTime(TypeDecorator):
    """Timezone-aware DateTime that always stores and returns UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetime rejected; attach a timezone (use utcnow()).")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def utcnow() -> datetime:
    """Timezone-aware 'now'. Never use datetime.utcnow() -- it returns naive values."""
    return datetime.now(UTC)


class TimestampMixin:
    """created_at / updated_at on every mutable table."""

    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class ActorMixin:
    """Who created / last touched the row. Nullable because background jobs and
    the eBay importer act without a logged-in user."""

    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class StrEnum(enum.StrEnum):
    """Base for every domain enum.

    Deliberately *not* SQLAlchemy's native Enum type: SQLite implements native
    enums as CHECK constraints, and a CHECK constraint cannot be altered later
    without rebuilding the whole table. A plain VARCHAR column plus a Python-side
    enum keeps "add a new order status" to a one-line code change.
    """


class IdMixin:
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
