"""Modul 3 -- Lager und Warenwirtschaft.

Design: the ``stock_movements`` table is the single source of truth and is
append-only. ``stock_levels`` is a derived cache of (article, location) quantities
that is updated inside the same transaction as the movement it follows. Any
disagreement between the two is a bug, and a test recomputes the cache from the
journal to prove they agree.

Why a cache at all: "verfuegbarer Bestand" is read on every listing page, every
sync run and every order import. Summing a journal that grows by thousands of rows
a month for each of those reads is the classic way to make a warehouse app slow
after a year.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    IdMixin,
    Money,
    Quantity,
    TimestampMixin,
    UtcDateTime,
)
from app.models.enums import PurchaseOrderStatus, ReservationStatus, StocktakeStatus


class StorageLocation(IdMixin, TimestampMixin, Base):
    """Regal / Fach / Box. Free-form hierarchy, one code per physical place."""

    __tablename__ = "storage_locations"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="SET NULL"), nullable=True
    )
    # Drives the walking order on a pick list (Modul 5). Lower runs first.
    pick_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Wareneingangszone / Retourenplatz -- excluded from the "available" total.
    is_sellable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    parent: Mapped["StorageLocation | None"] = relationship(
        remote_side="StorageLocation.id"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<StorageLocation {self.code}>"


class StockLevel(IdMixin, TimestampMixin, Base):
    """Derived cache: physical quantity of one article at one location."""

    __tablename__ = "stock_levels"
    __table_args__ = (
        UniqueConstraint("article_id", "location_id", name="uq_stock_levels_article_id"),
        Index("ix_stock_levels_location", "location_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"),
                                              nullable=False)

    article: Mapped["Article"] = relationship()  # noqa: F821
    location: Mapped[StorageLocation] = relationship()


class StockMovement(IdMixin, Base):
    """Append-only stock journal.

    No TimestampMixin: there is no ``updated_at`` because a row is never updated.
    A wrong booking is corrected by writing a compensating movement, exactly like
    a ledger. The service layer has no update or delete method for this table.

    ``reference_type`` / ``reference_id`` are an intentionally loose pointer to the
    triggering document (order, purchase order, stocktake, return). A hard FK per
    source would mean six nullable columns and a new migration per document type.
    """

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_article_time", "article_id", "booked_at"),
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    # Signed: +5 goods receipt, -1 sale. Keeps SUM() over the journal meaningful.
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    # Stock level at this location *after* this movement. Redundant on purpose:
    # it makes the journal auditable on its own, without replaying it.
    quantity_after: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    # Net unit cost at the time of booking -- needed for the weighted average and
    # for valuing stock at a past date.
    unit_cost_net: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)

    booked_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    article: Mapped["Article"] = relationship()  # noqa: F821
    location: Mapped[StorageLocation] = relationship()


class StockReservation(IdMixin, TimestampMixin, Base):
    """Reserved quantity for an open order line.

    verfuegbar = physischer Bestand - Summe offener Reservierungen.
    Kept as rows rather than a counter so a cancelled order can release exactly
    its own reservation without arithmetic on a shared number.
    """

    __tablename__ = "stock_reservations"
    __table_args__ = (
        Index("ix_stock_reservations_article_status", "article_id", "status"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False
    )
    order_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_lines.id", ondelete="CASCADE"), nullable=True, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReservationStatus.OPEN.value, nullable=False
    )
    released_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    article: Mapped["Article"] = relationship()  # noqa: F821


class PurchaseOrder(IdMixin, TimestampMixin, Base):
    """Lieferantenbestellung. Goods receipts are booked against its lines."""

    __tablename__ = "purchase_orders"

    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=PurchaseOrderStatus.DRAFT.value, nullable=False, index=True
    )
    ordered_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    expected_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    supplier_reference: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    shipping_cost_net: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    supplier: Mapped["Supplier"] = relationship()  # noqa: F821
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity_ordered: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    # Incremented by each goods receipt; partial deliveries just leave it short.
    quantity_received: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"),
                                                       nullable=False)
    unit_price_net: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    article: Mapped["Article"] = relationship()  # noqa: F821

    @property
    def quantity_open(self) -> Decimal:
        return max(Decimal("0"), self.quantity_ordered - self.quantity_received)


class Stocktake(IdMixin, TimestampMixin, Base):
    """Inventur. Closing it writes the differences as STOCKTAKE movements."""

    __tablename__ = "stocktakes"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=StocktakeStatus.OPEN.value, nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    lines: Mapped[list["StocktakeLine"]] = relationship(
        back_populates="stocktake", cascade="all, delete-orphan"
    )


class StocktakeLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "stocktake_lines"
    __table_args__ = (
        UniqueConstraint("stocktake_id", "article_id", "location_id",
                         name="uq_stocktake_lines_stocktake_id"),
    )

    stocktake_id: Mapped[int] = mapped_column(
        ForeignKey("stocktakes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="RESTRICT"), nullable=False
    )
    # Snapshot taken when the count list was generated -- the difference must be
    # calculated against what the system believed *then*, not at closing time.
    quantity_expected: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    quantity_counted: Mapped[Decimal | None] = mapped_column(Quantity(), nullable=True)
    counted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    counted_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    stocktake: Mapped[Stocktake] = relationship(back_populates="lines")
    article: Mapped["Article"] = relationship()  # noqa: F821
    location: Mapped[StorageLocation] = relationship()

    @property
    def difference(self) -> Decimal | None:
        if self.quantity_counted is None:
            return None
        return self.quantity_counted - self.quantity_expected
