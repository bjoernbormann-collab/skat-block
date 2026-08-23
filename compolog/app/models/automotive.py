"""Modul 1 -- Automotive-spezifische Stammdaten.

This is the part that differentiates the shop, so it gets real tables rather than
a JSON blob: OE numbers and fitments have to be searchable, and the eBay
Compatibility payload (Modul 2) is generated straight from the fitment rows.
"""

from __future__ import annotations

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

from app.models.base import Base, IdMixin, Measure, TimestampMixin


class OeNumber(IdMixin, TimestampMixin, Base):
    """A manufacturer's original part number.

    Its own table because one OE number legitimately maps to several of our
    articles (a connector housing sold both loose and as a repair kit), and the
    reverse is just as common.

    ``normalised`` strips spaces, dots and dashes and upper-cases the rest, so a
    search for "1J0 973 722" finds "1J0973722". Always search on this column.
    """

    __tablename__ = "oe_numbers"
    __table_args__ = (
        UniqueConstraint("normalised", "brand", name="uq_oe_numbers_normalised"),
        Index("ix_oe_numbers_normalised", "normalised"),
    )

    number: Mapped[str] = mapped_column(String(64), nullable=False)
    normalised: Mapped[str] = mapped_column(String(64), nullable=False)
    brand: Mapped[str] = mapped_column(String(64), default="", nullable=False)  # VAG, BMW…

    articles: Mapped[list["ArticleOeNumber"]] = relationship(
        back_populates="oe_number", cascade="all, delete-orphan"
    )

    @staticmethod
    def normalise(raw: str) -> str:
        """Canonical form used for lookups and duplicate detection."""
        return "".join(ch for ch in raw.upper() if ch.isalnum())


class ArticleOeNumber(IdMixin, TimestampMixin, Base):
    """n:m between article and OE number."""

    __tablename__ = "article_oe_numbers"
    __table_args__ = (
        UniqueConstraint("article_id", "oe_number_id", name="uq_article_oe_numbers_article_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    oe_number_id: Mapped[int] = mapped_column(
        ForeignKey("oe_numbers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # True for the number the part is actually sold as, False for "also fits".
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    article: Mapped["Article"] = relationship(back_populates="oe_numbers")  # noqa: F821
    oe_number: Mapped[OeNumber] = relationship(back_populates="articles")


class CrossReference(IdMixin, TimestampMixin, Base):
    """Competitor / aftermarket equivalent of one of our articles."""

    __tablename__ = "cross_references"
    __table_args__ = (
        Index("ix_cross_references_normalised", "normalised"),
        UniqueConstraint("article_id", "brand", "normalised",
                         name="uq_cross_references_article_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    brand: Mapped[str] = mapped_column(String(64), nullable=False)       # e.g. "Herth+Buss"
    reference_number: Mapped[str] = mapped_column(String(96), nullable=False)
    normalised: Mapped[str] = mapped_column(String(96), nullable=False)
    note: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    article: Mapped["Article"] = relationship(back_populates="cross_references")  # noqa: F821


class AttributeDefinition(IdMixin, TimestampMixin, Base):
    """The controlled vocabulary behind the key-value technical attributes.

    Free-form keys turn into "Polzahl", "Pol-Zahl" and "Anzahl Pole" within a
    fortnight, which then breaks the automatic Item-Specifics mapping. Every
    attribute key therefore has to exist here first.
    """

    __tablename__ = "attribute_definitions"

    code: Mapped[str] = mapped_column(String(48), unique=True, nullable=False)  # "pin_count"
    label_de: Mapped[str] = mapped_column(String(96), nullable=False)           # "Polzahl"
    unit: Mapped[str] = mapped_column(String(16), default="", nullable=False)   # "mm", "A", "°C"
    data_type: Mapped[str] = mapped_column(String(16), default="text", nullable=False)
    # Default mapping target for the eBay Taxonomy item specific, e.g.
    # "Anzahl der Anschlüsse". Per-category overrides live in Modul 2.
    ebay_aspect_name: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Show in the generated listing description / attribute table.
    show_in_listing: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    values: Mapped[list["ArticleAttribute"]] = relationship(back_populates="definition")


class ArticleAttribute(IdMixin, TimestampMixin, Base):
    """Technisches Attribut eines Artikels (Polzahl, Rastermass, Farbe, …).

    Both ``value_text`` and ``value_number`` are kept: text is what gets printed
    and sent to eBay, the number is what makes "Rastermass zwischen 2 und 3 mm"
    a usable filter later.
    """

    __tablename__ = "article_attributes"
    __table_args__ = (
        UniqueConstraint("article_id", "definition_id",
                         name="uq_article_attributes_article_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("attribute_definitions.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    value_text: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    value_number: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    article: Mapped["Article"] = relationship(back_populates="attributes")  # noqa: F821
    definition: Mapped[AttributeDefinition] = relationship(back_populates="values")


class Vehicle(IdMixin, TimestampMixin, Base):
    """One vehicle variant. Deduplicated so a fitment list is cheap to maintain.

    ``year_from`` / ``year_to`` are stored as YYYYMM integers (e.g. 200403) because
    German vehicle data is month-precise ("ab 03/2004") and a DATE would imply a
    day we do not have.
    """

    __tablename__ = "vehicles"
    __table_args__ = (
        UniqueConstraint("make", "model", "variant", "engine_code", "year_from", "year_to",
                         name="uq_vehicles_make"),
        Index("ix_vehicles_make_model", "make", "model"),
    )

    make: Mapped[str] = mapped_column(String(64), nullable=False)          # Volkswagen
    model: Mapped[str] = mapped_column(String(96), nullable=False)         # Golf V
    variant: Mapped[str] = mapped_column(String(96), default="", nullable=False)  # 1.9 TDI
    engine_code: Mapped[str] = mapped_column(String(32), default="", nullable=False)  # BKC
    year_from: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 200310
    year_to: Mapped[int | None] = mapped_column(Integer, nullable=True)    # 200902
    body_type: Mapped[str] = mapped_column(String(48), default="", nullable=False)
    # eBay's own vehicle identifier (K-Type / ePID). Cached after the first
    # successful compatibility push so later updates are exact matches.
    ebay_epid: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    ktype: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    fitments: Mapped[list["ArticleFitment"]] = relationship(
        back_populates="vehicle", cascade="all, delete-orphan"
    )

    @property
    def display_name(self) -> str:
        parts = [self.make, self.model, self.variant, self.engine_code]
        return " ".join(p for p in parts if p)


class ArticleFitment(IdMixin, TimestampMixin, Base):
    """n:m article <-> vehicle, with an optional restriction note."""

    __tablename__ = "article_fitments"
    __table_args__ = (
        UniqueConstraint("article_id", "vehicle_id", name="uq_article_fitments_article_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # "nur Fahrerseite", "bis Fahrgestellnummer …" -- goes into the eBay notes field.
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    article: Mapped["Article"] = relationship(back_populates="fitments")  # noqa: F821
    vehicle: Mapped[Vehicle] = relationship(back_populates="fitments")
