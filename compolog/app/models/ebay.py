"""Modul 2 -- eBay-Integration (Datenmodell).

Only the persistence side lives here; the API client follows in the eBay module
itself. A few notes that matter for the schema:

* eBay's Sell APIs are keyed by *your* SKU. That is why ``Article.sku`` is unique
  and immutable in practice -- changing it orphans the eBay inventory item.
* An Inventory Item (the product data) and an Offer (price, quantity, category,
  policies) are separate objects with separate lifecycles. They therefore get
  separate columns, not one "listing id".
* Every call is logged in ``ebay_api_calls``. That table grows fast; it is the
  first candidate for a retention job, and the raw bodies are truncated.
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

from app.models.base import Base, IdMixin, Money, TimestampMixin, UtcDateTime
from app.models.enums import EbayEnvironment, EbayListingStatus, TaskStatus


class EbayCredential(IdMixin, TimestampMixin, Base):
    """OAuth tokens for one eBay account and environment.

    Client id and secret stay in the .env. What is stored here is the *user*
    access and refresh token, which only exist after an interactive consent and
    cannot be put in a config file.

    Encryption: the token columns hold values encrypted with a key derived from
    SECRET_KEY (see app/services/crypto.py, delivered with the eBay module). The
    database file is therefore not enough to act on the account -- but note that
    an attacker with both the database and the .env has everything, so the .env
    must not be in the backup that leaves the house.
    """

    __tablename__ = "ebay_credentials"
    __table_args__ = (
        UniqueConstraint("environment", "ebay_user_id", name="uq_ebay_credentials_environment"),
    )

    environment: Mapped[str] = mapped_column(
        String(16), default=EbayEnvironment.SANDBOX.value, nullable=False
    )
    ebay_user_id: Mapped[str] = mapped_column(String(96), default="", nullable=False)
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime,
                                                                      nullable=True)
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # eBay refresh tokens live ~18 months and CANNOT be refreshed automatically --
    # they need a new interactive consent. The dashboard warns well before this.
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime,
                                                                       nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class ListingTemplate(IdMixin, TimestampMixin, Base):
    """HTML description template with placeholders.

    Placeholders: {{titel}}, {{kurzbeschreibung}}, {{langbeschreibung}},
    {{oe_nummern}}, {{tech_attribute}}, {{fitment_tabelle}}, {{hersteller}},
    {{mpn}}, {{sku}}, {{bilder}}.

    Rendering happens at publish time, so editing the template and re-publishing
    updates every affected listing -- that is the whole point of having one.
    """

    __tablename__ = "listing_templates"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    html: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)


class EbayCategoryMapping(IdMixin, TimestampMixin, Base):
    """Warengruppe -> eBay category, plus the cached required item specifics.

    ``required_aspects_json`` is the Taxonomy API's answer for this category,
    cached because it changes rarely and the call is expensive. ``aspects_fetched_at``
    drives a refresh; stale data is the usual cause of a surprise publish failure.
    """

    __tablename__ = "ebay_category_mappings"
    __table_args__ = (
        UniqueConstraint("product_group_id", "marketplace_id",
                         name="uq_ebay_category_mappings_product_group_id"),
    )

    product_group_id: Mapped[int] = mapped_column(
        ForeignKey("product_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marketplace_id: Mapped[str] = mapped_column(String(32), default="EBAY_DE", nullable=False)
    category_id: Mapped[str] = mapped_column(String(32), nullable=False)
    category_name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    category_tree_id: Mapped[str] = mapped_column(String(16), default="", nullable=False)
    required_aspects_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    aspects_fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Per-category override of AttributeDefinition.ebay_aspect_name:
    # {"pin_count": "Anzahl der Pins"}.
    aspect_mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class EbayListing(IdMixin, TimestampMixin, Base):
    """Local mirror of one article's presence on eBay.

    One row per (article, marketplace). Holds the ids of both eBay objects and the
    last values pushed, so the sync job can tell 'nothing changed' from 'push
    failed' without calling the API.
    """

    __tablename__ = "ebay_listings"
    __table_args__ = (
        UniqueConstraint("article_id", "marketplace_id",
                         name="uq_ebay_listings_article_id"),
        Index("ix_ebay_listings_status", "status"),
        Index("ix_ebay_listings_offer", "offer_id"),
    )

    article_id: Mapped[int] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), nullable=False
    )
    marketplace_id: Mapped[str] = mapped_column(String(32), default="EBAY_DE", nullable=False)
    environment: Mapped[str] = mapped_column(
        String(16), default=EbayEnvironment.SANDBOX.value, nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(24), default=EbayListingStatus.NOT_LISTED.value, nullable=False
    )

    # eBay object identifiers. The inventory item is addressed by SKU, so there is
    # no separate id for it -- only a flag saying it has been created.
    inventory_item_created: Mapped[bool] = mapped_column(Boolean, default=False,
                                                          nullable=False)
    inventory_group_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    offer_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    listing_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # legacy item id
    listing_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Last successfully pushed values -- the sync job's change detector.
    #
    # Quantities here stay Integer while the rest of the system uses decimals:
    # eBay's Inventory API only accepts whole numbers, so these columns mirror
    # what eBay actually holds. The client floors on the way out -- offering
    # 2.7 m of cable as "3" would oversell.
    last_pushed_price: Mapped[Decimal | None] = mapped_column(Money(), nullable=True)
    last_pushed_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_pushed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_pulled_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # Quantity eBay reports back; a mismatch with our own is what OUT_OF_SYNC means.
    channel_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    last_error_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("listing_templates.id", ondelete="SET NULL"), nullable=True
    )

    article: Mapped["Article"] = relationship()  # noqa: F821


class EbayApiCall(IdMixin, Base):
    """Full audit trail of every eBay HTTP call.

    Append-only, no updated_at. Bodies are stored truncated (see the client) --
    a 2 MB bulk inventory payload in the log helps nobody and fills the disk.
    """

    __tablename__ = "ebay_api_calls"
    __table_args__ = (
        Index("ix_ebay_api_calls_created", "created_at"),
        Index("ix_ebay_api_calls_endpoint", "endpoint"),
    )

    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    # Logical operation, used for rate-limit bucketing: "inventory.createOrReplace".
    operation: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    request_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Correlates a call with the article/order it was made for.
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class EbayRateLimit(IdMixin, TimestampMixin, Base):
    """Cached quota per API resource, from the Developer Analytics API.

    eBay's limits are per resource and reset daily. Reading them instead of
    guessing is what keeps a bulk publish from being cut off halfway.
    """

    __tablename__ = "ebay_rate_limits"
    __table_args__ = (
        UniqueConstraint("environment", "api_name", "resource_name",
                         name="uq_ebay_rate_limits_environment"),
    )

    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    api_name: Mapped[str] = mapped_column(String(64), nullable=False)      # "sell.inventory"
    resource_name: Mapped[str] = mapped_column(String(96), nullable=False)
    limit_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reset_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class SyncTask(IdMixin, TimestampMixin, Base):
    """Retry queue. Nothing fails silently -- a failed call lands here.

    ``payload_json`` holds everything needed to retry without recomputing, so a
    task stays valid even if the source record changed in the meantime.
    ``next_attempt_at`` implements the exponential backoff.
    """

    __tablename__ = "sync_tasks"
    __table_args__ = (
        Index("ix_sync_tasks_status_next", "status", "next_attempt_at"),
    )

    task_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(16), default=TaskStatus.PENDING.value, nullable=False
    )
    direction: Mapped[str] = mapped_column(String(8), default="push", nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
