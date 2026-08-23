"""Modul 7 -- Versand."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, Measure, Money, TimestampMixin, UtcDateTime
from app.models.enums import ShipmentStatus


class Carrier(IdMixin, TimestampMixin, Base):
    """DHL today, DPD/GLS later. Credentials stay in the .env, not here."""

    __tablename__ = "carriers"

    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)  # "dhl"
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # URL template with {tracking_number}; also reported to eBay.
    tracking_url_template: Mapped[str] = mapped_column(String(255), default="",
                                                        nullable=False)
    # eBay's shipping carrier enum value ("DHL", "DEUTSCHE_POST") for the
    # Fulfillment API createShippingFulfillment call.
    ebay_carrier_code: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    products: Mapped[list["ShippingProduct"]] = relationship(back_populates="carrier")


class ShippingProduct(IdMixin, TimestampMixin, Base):
    """A concrete product of a carrier: DHL Paket, Warenpost, Kleinpaket."""

    __tablename__ = "shipping_products"

    carrier_id: Mapped[int] = mapped_column(
        ForeignKey("carriers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(32), nullable=False)   # "V01PAK"
    name: Mapped[str] = mapped_column(String(96), nullable=False)
    max_weight_gram: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    base_price_gross: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    carrier: Mapped[Carrier] = relationship(back_populates="products")


class Shipment(IdMixin, TimestampMixin, Base):
    """One parcel. An order can have several (Teillieferung, Nachlieferung)."""

    __tablename__ = "shipments"
    __table_args__ = (
        Index("ix_shipments_tracking", "tracking_number"),
    )

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    carrier_id: Mapped[int | None] = mapped_column(
        ForeignKey("carriers.id", ondelete="SET NULL"), nullable=True
    )
    shipping_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("shipping_products.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=ShipmentStatus.DRAFT.value, nullable=False, index=True
    )
    tracking_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    weight_gram: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    length_mm: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    height_mm: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    cost_gross: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    label_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    label_created_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)

    # Reporting the tracking number back to eBay is rating-relevant, so its state
    # is tracked explicitly instead of being assumed after a successful call.
    reported_to_channel_at: Mapped[datetime | None] = mapped_column(UtcDateTime,
                                                                     nullable=True)
    channel_fulfillment_id: Mapped[str] = mapped_column(String(64), default="",
                                                          nullable=False)
    channel_report_error: Mapped[str] = mapped_column(Text, default="", nullable=False)

    order: Mapped["Order"] = relationship()  # noqa: F821
    carrier: Mapped[Carrier | None] = relationship()
    lines: Mapped[list["ShipmentLine"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan"
    )


class ShipmentLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "shipment_lines"

    shipment_id: Mapped[int] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("order_lines.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shipment: Mapped[Shipment] = relationship(back_populates="lines")
    order_line: Mapped["OrderLine"] = relationship()  # noqa: F821
