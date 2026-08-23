"""Modul 1 -- Artikelstammdaten (PIM).

Variant handling: a PARENT article groups CHILD articles (same Bauform, different
Polzahl). Stock is *only ever* kept on STANDALONE and CHILD articles -- the parent
is a pure grouping record and maps to an eBay Inventory Item Group. This is
enforced in the service layer and asserted in tests.
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

from app.models.base import (
    ActorMixin,
    Base,
    IdMixin,
    Measure,
    Money,
    Percent,
    Quantity,
    TimestampMixin,
)
from app.models.enums import ArticleCondition, ArticleKind


class ProductGroup(IdMixin, TimestampMixin, Base):
    """Eigene Warengruppe. Carries the eBay category mapping (Modul 2)."""

    __tablename__ = "product_groups"

    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_groups.id", ondelete="SET NULL"), nullable=True
    )
    # Filled in once per group and reused for every listing in it (Modul 2).
    ebay_category_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ebay_category_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # eBay business policy ids (Metadata API); overridable per article.
    ebay_fulfillment_policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ebay_payment_policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ebay_return_policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("listing_templates.id", ondelete="SET NULL"), nullable=True
    )

    parent: Mapped["ProductGroup | None"] = relationship(remote_side="ProductGroup.id")
    articles: Mapped[list["Article"]] = relationship(back_populates="product_group")


class Supplier(IdMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    customer_number: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    contact_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    street: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    zip_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(2), default="DE", nullable=False)
    vat_id: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    default_lead_time_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Manufacturer(IdMixin, TimestampMixin, Base):
    """Hersteller (TE Connectivity, Aptiv/Delphi, Yazaki, Molex, …)."""

    __tablename__ = "manufacturers"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    website: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Article(IdMixin, TimestampMixin, ActorMixin, Base):
    __tablename__ = "articles"
    __table_args__ = (
        UniqueConstraint("sku", name="uq_articles_sku"),
        Index("ix_articles_mpn", "mpn"),
        Index("ix_articles_title", "title"),
    )

    # ------------------------------------------------------------ identification
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    ean: Mapped[str | None] = mapped_column(String(14), nullable=True, index=True)
    mpn: Mapped[str | None] = mapped_column(String(96), nullable=True)
    manufacturer_id: Mapped[int | None] = mapped_column(
        ForeignKey("manufacturers.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # -------------------------------------------------------------------- texts
    # 80 chars is eBay's hard limit for the listing title; enforced at the DB level
    # so a bad import cannot create an article that can never be published.
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    short_description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    long_description: Mapped[str] = mapped_column(Text, default="", nullable=False)  # HTML

    # ------------------------------------------------------------------ variants
    kind: Mapped[str] = mapped_column(
        String(16), default=ArticleKind.STANDALONE.value, nullable=False, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("articles.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    # Which technical attributes distinguish the children, e.g. "Polzahl,Farbe".
    # Stored on the parent, used to build the eBay Inventory Item Group aspects.
    variant_axis: Mapped[str] = mapped_column(String(255), default="", nullable=False)

    # ---------------------------------------------------------- logistics / customs
    weight_gram: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    length_mm: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    width_mm: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    height_mm: Mapped[Decimal | None] = mapped_column(Measure(), nullable=True)
    # Base units per pack: 1 for loose parts, 25 for a 25 m ring of cable.
    packaging_unit: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("1"),
                                                    nullable=False)
    hs_code: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    country_of_origin: Mapped[str] = mapped_column(String(2), default="", nullable=False)

    # -------------------------------------------------------------------- pricing
    # Purchase price is net, sales price is gross -- that is how the trade thinks
    # and how eBay wants it. Net/VAT are derived, never stored redundantly.
    purchase_price_net: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    sales_price_gross: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    vat_rate: Mapped[Decimal] = mapped_column(Percent(), default=Decimal("19.00"),
                                              nullable=False)
    # Rolling weighted average purchase price, maintained by the goods-receipt
    # booking (Modul 3) and used for the margin report (Modul 8).
    average_cost_net: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)

    # ------------------------------------------------------------------- sourcing
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    supplier_sku: Mapped[str] = mapped_column(String(96), default="", nullable=False)

    # --------------------------------------------------------------- classification
    product_group_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_groups.id", ondelete="SET NULL"), nullable=True, index=True
    )
    condition: Mapped[str] = mapped_column(
        String(16), default=ArticleCondition.NEW.value, nullable=False
    )

    # ---------------------------------------------------------------- warehousing
    min_stock: Mapped[Decimal] = mapped_column(Quantity(), default=Decimal("0"),
                                               nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    internal_note: Mapped[str] = mapped_column(Text, default="", nullable=False)

    # ------------------------------------------------------------- relationships
    manufacturer: Mapped[Manufacturer | None] = relationship()
    supplier: Mapped[Supplier | None] = relationship()
    product_group: Mapped[ProductGroup | None] = relationship(back_populates="articles")
    parent: Mapped["Article | None"] = relationship(
        remote_side="Article.id", back_populates="children"
    )
    children: Mapped[list["Article"]] = relationship(back_populates="parent")

    images: Mapped[list["ArticleImage"]] = relationship(
        back_populates="article", cascade="all, delete-orphan",
        order_by="ArticleImage.sort_order",
    )
    oe_numbers: Mapped[list["ArticleOeNumber"]] = relationship(  # noqa: F821
        back_populates="article", cascade="all, delete-orphan"
    )
    cross_references: Mapped[list["CrossReference"]] = relationship(  # noqa: F821
        back_populates="article", cascade="all, delete-orphan"
    )
    attributes: Mapped[list["ArticleAttribute"]] = relationship(  # noqa: F821
        back_populates="article", cascade="all, delete-orphan",
        order_by="ArticleAttribute.sort_order",
    )
    fitments: Mapped[list["ArticleFitment"]] = relationship(  # noqa: F821
        back_populates="article", cascade="all, delete-orphan"
    )

    @property
    def carries_stock(self) -> bool:
        """Variant parents are grouping records only."""
        return self.kind != ArticleKind.PARENT.value

    @property
    def sales_price_net(self) -> Decimal | None:
        """Derived, never stored -- avoids the two values drifting apart."""
        if self.sales_price_gross is None:
            return None
        divisor = Decimal(1) + (self.vat_rate / Decimal(100))
        return (self.sales_price_gross / divisor).quantize(Decimal("0.0001"))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Article {self.sku} {self.title[:30]!r}>"


class ArticleImage(IdMixin, TimestampMixin, Base):
    """Images live on disk; the database only holds the relative path.

    ``ebay_image_url`` caches the URL returned by the eBay Picture Service so an
    offer update does not re-upload the same bytes (Modul 2). It is invalidated by
    clearing it whenever ``checksum`` changes.
    """

    __tablename__ = "article_images"
    __table_args__ = (
        Index("ix_article_images_article", "article_id", "sort_order"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    # Relative to settings.image_dir, e.g. "CL-001234/front.jpg".
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), default="image/jpeg", nullable=False)
    byte_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    alt_text: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    ebay_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    article: Mapped[Article] = relationship(back_populates="images")
