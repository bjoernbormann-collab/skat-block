"""Modul 8 -- Gebuehren, Auswertung, Buchhaltungsexport."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, Money, Percent, TimestampMixin, UtcDateTime


class FeeRule(IdMixin, TimestampMixin, Base):
    """Marketplace fee model, kept configurable because eBay keeps changing it.

    The 2026 structure is a fixed amount per sale plus a percentage of the total,
    varying by category, with a cap. All four parts are here so a rate change is a
    form edit rather than a code change. ``valid_from``/``valid_to`` keep historic
    orders costed with the rules that applied at the time.
    """

    __tablename__ = "fee_rules"
    __table_args__ = (
        Index("ix_fee_rules_validity", "channel_id", "valid_from"),
    )

    channel_id: Mapped[int] = mapped_column(
        ForeignKey("sales_channels.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Empty = applies to every category not covered by a more specific rule.
    ebay_category_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    product_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_groups.id", ondelete="SET NULL"), nullable=True
    )
    fixed_fee_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                      nullable=False)
    percent_fee: Mapped[Decimal] = mapped_column(Percent(), default=Decimal("0"),
                                                  nullable=False)
    # Whether the percentage applies to the shipping amount as well (eBay: yes).
    applies_to_shipping: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_fee_gross: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class OrderFee(IdMixin, TimestampMixin, Base):
    """Actual fee booked against an order.

    Two sources: ``estimated`` (computed from FeeRule at import time, so the
    dashboard shows a margin immediately) and the real amount pulled from eBay's
    transaction/payout data later. Both are kept -- the difference is worth seeing.
    """

    __tablename__ = "order_fees"

    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fee_type: Mapped[str] = mapped_column(String(48), nullable=False)  # "final_value_fee"
    amount_gross: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    is_estimated: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    channel_reference: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    booked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    order: Mapped["Order"] = relationship()  # noqa: F821


class TaxRate(IdMixin, TimestampMixin, Base):
    """VAT rate per country, for the OSS case.

    Selling B2C above the EU-wide 10.000 EUR threshold means charging the *buyer's*
    country rate and declaring it via OSS. This table is the groundwork; the OSS
    report itself is part of Modul 8's delivery.
    """

    __tablename__ = "tax_rates"
    __table_args__ = (
        UniqueConstraint("country", "rate_type", "valid_from",
                         name="uq_tax_rates_country"),
    )

    country: Mapped[str] = mapped_column(String(2), nullable=False)
    rate_type: Mapped[str] = mapped_column(String(16), default="standard", nullable=False)
    rate: Mapped[Decimal] = mapped_column(Percent(), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    # DATEV account for this rate, used by the booking-stack export.
    datev_account: Mapped[str] = mapped_column(String(16), default="", nullable=False)


class AccountingExport(IdMixin, TimestampMixin, Base):
    """Record of a DATEV / XLSX export handed to the accountant.

    Kept so the same period is not exported twice with different content, and so
    it is provable what was handed over when.
    """

    __tablename__ = "accounting_exports"

    export_type: Mapped[str] = mapped_column(String(24), nullable=False)  # "datev", "xlsx"
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_gross: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                  nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
