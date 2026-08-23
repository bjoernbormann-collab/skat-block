"""Modul 6 -- Belege (Rechnung, Lieferschein, Gutschrift, Storno).

GoBD in three rules, enforced by this schema:

1. Unveraenderbarkeit -- a Document row and its PDF are written once. There is no
   update path; ``finalised_at`` marks the point of no return. Corrections happen
   through a CANCELLATION document that points back via ``cancels_document_id``.
2. Nachvollziehbarkeit -- the PDF's SHA-256 is stored so a later change to the file
   on disk is detectable.
3. Vollstaendigkeit -- number ranges are gapless (see NumberRange and
   app/services/numbering.py).

The line items are copied into ``document_lines`` rather than referenced from the
order: an invoice must still print correctly in eight years, when the article has
long been renamed or deleted.
"""

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

from app.models.base import (
    Base,
    IdMixin,
    Money,
    Percent,
    Quantity,
    TimestampMixin,
    UtcDateTime,
)


class NumberRange(IdMixin, TimestampMixin, Base):
    """A gapless counter.

    One row per (code, period). ``period`` is "" for a continuous range or "2026"
    for a yearly one -- yearly ranges are what most German accountants expect for
    invoices. The counter is advanced by a single UPDATE inside the caller's
    transaction; see app/services/numbering.py for why that is the only safe way.
    """

    __tablename__ = "number_ranges"
    __table_args__ = (
        UniqueConstraint("code", "period", name="uq_number_ranges_code"),
    )

    code: Mapped[str] = mapped_column(String(32), nullable=False)   # "invoice", "order", …
    period: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    # Python format string, e.g. "RE-{year}-{counter:05d}".
    schema: Mapped[str] = mapped_column(String(64), nullable=False)
    current_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Restart at 1 every calendar year (creates a new row with the new period).
    yearly_reset: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str] = mapped_column(String(160), default="", nullable=False)


class Document(IdMixin, TimestampMixin, Base):
    """An issued document. Immutable once ``finalised_at`` is set."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("number", name="uq_documents_number"),
        Index("ix_documents_type_date", "document_type", "document_date"),
        Index("ix_documents_order", "order_id"),
    )

    number: Mapped[str] = mapped_column(String(32), nullable=False)
    document_type: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=True
    )
    return_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("return_requests.id", ondelete="RESTRICT"), nullable=True
    )

    # ---------------------------------------------------- §14 UStG mandatory data
    document_date: Mapped[date] = mapped_column(Date, nullable=False)      # Rechnungsdatum
    # Leistungsdatum. §14 Abs. 4 Nr. 6 UStG requires it even when it equals the
    # invoice date; the template prints "Leistungsdatum entspricht Rechnungsdatum".
    service_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Full recipient snapshot -- addresses can be edited, invoices cannot.
    recipient_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    recipient_address: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recipient_vat_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    recipient_country: Mapped[str] = mapped_column(String(2), default="DE", nullable=False)
    # Seller snapshot: firmierung/USt-IdNr. at issue time, copied from settings.
    issuer_snapshot: Mapped[str] = mapped_column(Text, default="", nullable=False)  # JSON

    # -------------------------------------------------------------------- totals
    net_total: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    vat_total: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"), nullable=False)
    gross_total: Mapped[Decimal] = mapped_column(Money(), default=Decimal("0"),
                                                  nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    # Reason a document carries no VAT: "kleinunternehmer", "innergemeinschaftlich",
    # "reverse_charge", "ausfuhr". Empty for normal domestic sales.
    tax_exemption_reason: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    # ------------------------------------------------------------- immutability
    finalised_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Relative to settings.document_dir: "2026/03/RE-2026-00042.pdf".
    pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # ZUGFeRD/XRechnung XML, embedded in the PDF/A-3 and kept here for re-export.
    einvoice_xml_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    einvoice_profile: Mapped[str] = mapped_column(String(32), default="", nullable=False)

    # ------------------------------------------------------------- cancellation
    cancels_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True
    )
    cancelled_by_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=True
    )

    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    order: Mapped["Order | None"] = relationship()  # noqa: F821
    lines: Mapped[list["DocumentLine"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
        order_by="DocumentLine.position",
    )
    cancels: Mapped["Document | None"] = relationship(
        remote_side="Document.id", foreign_keys=[cancels_document_id]
    )

    @property
    def is_finalised(self) -> bool:
        return self.finalised_at is not None

    @property
    def is_cancelled(self) -> bool:
        return self.cancelled_by_document_id is not None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Document {self.document_type} {self.number}>"


class DocumentLine(IdMixin, TimestampMixin, Base):
    __tablename__ = "document_lines"
    __table_args__ = (
        UniqueConstraint("document_id", "position", name="uq_document_lines_document_id"),
    )

    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    # Snapshot only -- article_id is a convenience link for reporting, never a
    # source of printed data.
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="SET NULL"), nullable=True
    )
    sku: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Quantity(), nullable=False)
    # "Stk", "m", "Satz" -- printed on the document next to the quantity.
    unit: Mapped[str] = mapped_column(String(16), default="Stk", nullable=False)
    unit_price_net: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    vat_rate: Mapped[Decimal] = mapped_column(Percent(), nullable=False)
    line_net: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    line_vat: Mapped[Decimal] = mapped_column(Money(), nullable=False)
    line_gross: Mapped[Decimal] = mapped_column(Money(), nullable=False)

    document: Mapped[Document] = relationship(back_populates="lines")
