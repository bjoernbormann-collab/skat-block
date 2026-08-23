"""Modul 4 -- Auftragsabwicklung.

Channel-agnostic on purpose. Everything eBay-specific is either in
``sales_channels`` (one row per connected marketplace account) or in the
``channel_*`` columns, which hold whatever identifier the channel uses. Adding
Kleinanzeigen or a webshop later means one new SalesChannel row plus an importer,
not a schema change.

Address data is *copied* into the order rather than referenced from a customer
table. Marketplace buyers are not a CRM; the address as it was at the time of the
order is what has to appear on the invoice, and it must not change retroactively
when the buyer moves house.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    IdMixin,
    Money,
    Percent,
    Quantity,
    TimestampMixin,
    UtcDateTime,
)
from app.models.enums import (
    OrderStatus,
    PaymentStatus,
    ReturnStatus,
    SalesChannelType,
)


class SalesChannel(IdMixin, TimestampMixin, Base):
    """One connected selling account."""

    __tablename__ = "sales_channels"

    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)  # "ebay_de"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    channel_type: Mapped[str] = mapped_column(
        String(16), default=SalesChannelType.EBAY.value, nullable=False
    )
    marketplace_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Sandbox channels keep their orders out of the real reports.
    is_sandbox: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    orders: Mapped[list["Order"]] = relationship(back_populates="channel")


class Address(IdMixin, TimestampMixin, Base):
    """Immutable address snapshot belonging to exactly one order."""

    __tablename__ = "addresses"

    company: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    first_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    street: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    street2: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    zip_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    state: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="DE", nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    @property
    def full_name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p)


class Order(IdMixin, TimestampMixin, Base):
    """A shipping-level order.

    eBay hands out one order per transaction; several of them for the same buyer
    are merged into one Order here via ``merge_group_key`` so the warehouse packs
    once. Every original marketplace order id is preserved in
    ``OrderChannelReference`` -- the tracking number has to be reported back
    against each of them individually.
    """

    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_merge_group", "merge_group_key"),
    )

    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("sales_channels.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=OrderStatus.NEW.value, nullable=False, index=True
    )
    payment_status: Mapped[str] = mapped_column(
        String(24), default=PaymentStatus.PENDING.value, nullable=False, index=True
    )

    # ---------------------------------------------------------------- buyer data
    buyer_username: Mapped[str] = mapped_column(String(96), default="", nullable=False,
                                                index=True)
    buyer_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    shipping_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )
    billing_address_id: Mapped[int | None] = mapped_column(
        ForeignKey("addresses.id", ondelete="SET NULL"), nullable=True
    )

    # -------------------------------------------------------------------- money
    # Totals are stored, not derived: the marketplace's own total is authoritative
    # for the payout, and recomputing it from lines can differ by a cent through
    # eBay's own rounding.
    items_total_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                       nullable=False)
    shipping_total_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                          nullable=False)
    discount_total_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                          nullable=False)
    grand_total_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                        nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    # Marketplace fees, filled from the eBay payout/transaction data (Modul 8).
    channel_fee_total: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                        nullable=False)
    # What we actually paid the carrier (Modul 7), for the margin report.
    shipping_cost_actual: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                           nullable=False)

    # --------------------------------------------------------------- timestamps
    ordered_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # eBay's promised handover deadline -- drives the "muss heute raus" dashboard.
    ship_by_date: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # ------------------------------------------------------------------- other
    shipping_service: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    buyer_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    internal_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Set when several marketplace orders were combined; NULL for single orders.
    merge_group_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    channel: Mapped[SalesChannel] = relationship(back_populates="orders")
    shipping_address: Mapped[Address | None] = relationship(
        foreign_keys=[shipping_address_id]
    )
    billing_address: Mapped[Address | None] = relationship(foreign_keys=[billing_address_id])
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    channel_references: Mapped[list["OrderChannelReference"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Order {self.number} {self.status}>"


class OrderChannelReference(IdMixin, TimestampMixin, Base):
    """One marketplace order id contributing to this Order.

    Unique on (channel, channel_order_id) -- this is what makes the order import
    idempotent: re-importing the same eBay order is a no-op instead of a duplicate.
    """

    __tablename__ = "order_channel_references"
    __table_args__ = (
        UniqueConstraint("channel_id", "channel_order_id",
                         name="uq_order_channel_references_channel_id"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("sales_channels.id", ondelete="RESTRICT"), nullable=False
    )
    channel_order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # eBay's legacy "12-34567-89012" id, still shown to the buyer in messages.
    channel_legacy_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    raw_payload: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON as received

    order: Mapped[Order] = relationship(back_populates="channel_references")


class OrderLine(IdMixin, TimestampMixin, Base):
    """One sold position.

    ``article_id`` is nullable: an eBay order can arrive for a listing that is not
    (yet) linked to a PIM article. Such an order lands in the clarification list
    rather than being rejected -- losing an order because of a mapping gap is the
    worst possible failure mode.
    """

    __tablename__ = "order_lines"
    __table_args__ = (
        Index("ix_order_lines_article", "article_id"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot of what was sold, independent of later PIM edits.
    sku: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    unit_price_gross: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Percent(), default=Decimal("19.00"),
                                              nullable=False)
    line_total_gross: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    # Cost of goods at the moment of sale -- frozen here so the margin report does
    # not silently change when the average purchase price moves.
    unit_cost_net: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    channel_line_item_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    quantity_shipped: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"),
                                                      nullable=False)
    quantity_returned: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"),
                                                       nullable=False)

    order: Mapped[Order] = relationship(back_populates="lines")
    article: Mapped["Article | None"] = relationship()  # noqa: F821


class ReturnRequest(IdMixin, TimestampMixin, Base):
    """Retoure. Receiving it books stock back in and triggers a credit note."""

    __tablename__ = "return_requests"

    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(16), default=ReturnStatus.ANNOUNCED.value, nullable=False, index=True
    )
    channel_return_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    refund_amount_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                          nullable=False)
    # Whether the returned goods went back into sellable stock.
    restocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    order: Mapped[Order] = relationship()
    lines: Mapped[list["ReturnLine"]] = relationship(
        back_populates="return_request", cascade="all, delete-orphan"
    )


class ReturnLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "return_lines"

    return_request_id: Mapped[int] = mapped_column(
        ForeignKey("return_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    # Sellable again, or scrap? Decides whether stock is booked back at all.
    is_sellable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    condition_note: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    return_request: Mapped[ReturnRequest] = relationship(back_populates="lines")
    order_line: Mapped[OrderLine] = relationship()
