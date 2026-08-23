"""Modul 5 -- Kommissionierung."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, Quantity, TimestampMixin, UtcDateTime
from app.models.enums import PickLineStatus, PickListStatus


class PickList(IdMixin, TimestampMixin, Base):
    """One or many orders picked in a single walk (Batch-Picking).

    The link to orders is n:m via ``pick_list_orders`` so a batch can cover many
    orders and -- in the rare re-pick case -- one order can appear on a second list.
    """

    __tablename__ = "pick_lists"

    number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=PickListStatus.OPEN.value, nullable=False, index=True
    )
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    lines: Mapped[list["PickLine"]] = relationship(
        back_populates="pick_list", cascade="all, delete-orphan",
        order_by="PickLine.sort_order",
    )
    orders: Mapped[list["PickListOrder"]] = relationship(
        back_populates="pick_list", cascade="all, delete-orphan"
    )


class PickListOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "pick_list_orders"

    pick_list_id: Mapped[int] = mapped_column(
        ForeignKey("pick_lists.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True
    )

    pick_list: Mapped[PickList] = relationship(back_populates="orders")
    order: Mapped["Order"] = relationship()  # noqa: F821


class PickLine(IdMixin, TimestampMixin, Base):
    """One article to fetch from one location.

    ``sort_order`` is precomputed from StorageLocation.pick_sequence when the list
    is generated, so the mobile view and the PDF cannot disagree about the route.
    """

    __tablename__ = "pick_lines"
    __table_args__ = (
        Index("ix_pick_lines_list_sort", "pick_list_id", "sort_order"),
    )

    pick_list_id: Mapped[int] = mapped_column(
        ForeignKey("pick_lists.id", ondelete="CASCADE"), nullable=False
    )
    order_line_id: Mapped[int] = mapped_column(
        ForeignKey("order_lines.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    location_id: Mapped[int | None] = mapped_column(
        ForeignKey("storage_locations.id", ondelete="SET NULL"), nullable=True
    )
    quantity_requested: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    quantity_picked: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"),
                                                     nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=PickLineStatus.OPEN.value, nullable=False, index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Proof that the scanner, not a thumb, confirmed the position.
    scanned_code: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    scan_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    picked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    picked_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    short_reason: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    pick_list: Mapped[PickList] = relationship(back_populates="lines")
    article: Mapped["Article"] = relationship()  # noqa: F821
    order_line: Mapped["OrderLine"] = relationship()  # noqa: F821

    @property
    def quantity_open(self) -> Decimal:
        return max(Decimal("0"), self.quantity_requested - self.quantity_picked)
