"""All enumerations used across the domain.

Stored as plain strings (see StrEnum in base.py). Adding a value is a code change
only -- no migration needed.
"""

from __future__ import annotations

from app.models.base import StrEnum


class UserRole(StrEnum):
    ADMIN = "admin"              # full access
    WAREHOUSE = "warehouse"      # picking, goods receipt, stock counts only


class ArticleCondition(StrEnum):
    NEW = "new"
    USED = "used"
    REFURBISHED = "refurbished"


class ArticleKind(StrEnum):
    """Variant handling.

    STANDALONE  - normal article, carries stock
    PARENT      - variant parent, carries *no* stock, only groups children
    CHILD       - variant child, carries stock, points at a parent
    """

    STANDALONE = "standalone"
    PARENT = "parent"
    CHILD = "child"


class StockMovementType(StrEnum):
    """The immutable stock journal. Every quantity change is one of these."""

    GOODS_RECEIPT = "goods_receipt"        # Wareneingang
    SALE = "sale"                          # Verkauf
    RETURN = "return"                      # Retoure (customer -> stock)
    CORRECTION = "correction"              # manual correction with reason
    STOCKTAKE = "stocktake"                # Inventurdifferenz
    TRANSFER_OUT = "transfer_out"          # Umlagerung, source side
    TRANSFER_IN = "transfer_in"            # Umlagerung, target side
    SCRAP = "scrap"                        # Verschrottung / Bruch
    SUPPLIER_RETURN = "supplier_return"    # Rücksendung an Lieferanten


class ReservationStatus(StrEnum):
    OPEN = "open"
    RELEASED = "released"      # order cancelled -> reservation dropped
    CONSUMED = "consumed"      # picked and shipped -> became a SALE movement


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    ORDERED = "ordered"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CANCELLED = "cancelled"


class StocktakeStatus(StrEnum):
    OPEN = "open"
    COUNTING = "counting"
    CLOSED = "closed"          # differences booked, immutable afterwards


class SalesChannelType(StrEnum):
    """Channel-agnostic by design: eBay is just the first one."""

    EBAY = "ebay"
    MANUAL = "manual"
    OTHER = "other"


class OrderStatus(StrEnum):
    NEW = "new"                          # neu
    PAID = "paid"                        # bezahlt
    PICKING = "picking"                  # in Kommissionierung
    PICKED = "picked"                    # kommissioniert
    SHIPPED = "shipped"                  # versendet
    COMPLETED = "completed"              # abgeschlossen
    CANCELLED = "cancelled"              # storniert
    RETURNED = "returned"                # retourniert
    CLARIFICATION = "clarification"      # Klärungsfall, z.B. Fehlmenge beim Picken


class PaymentStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    PARTIALLY_REFUNDED = "partially_refunded"
    REFUNDED = "refunded"
    FAILED = "failed"


class PickListStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    PARTIAL = "partial"        # at least one line short-picked
    CANCELLED = "cancelled"


class PickLineStatus(StrEnum):
    OPEN = "open"
    PICKED = "picked"
    SHORT = "short"            # Fehlmenge
    SKIPPED = "skipped"


class DocumentType(StrEnum):
    INVOICE = "invoice"                # Rechnung
    DELIVERY_NOTE = "delivery_note"    # Lieferschein
    CREDIT_NOTE = "credit_note"        # Gutschrift
    CANCELLATION = "cancellation"      # Stornorechnung


class ReturnStatus(StrEnum):
    ANNOUNCED = "announced"
    RECEIVED = "received"
    INSPECTED = "inspected"
    REFUNDED = "refunded"
    REJECTED = "rejected"


class ShipmentStatus(StrEnum):
    DRAFT = "draft"
    LABEL_CREATED = "label_created"
    HANDED_OVER = "handed_over"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class EbayListingStatus(StrEnum):
    """State of the local mirror of an eBay listing."""

    NOT_LISTED = "not_listed"
    DRAFT = "draft"                # inventory item exists, offer not published
    PUBLISHED = "published"        # live on eBay
    ENDED = "ended"
    OUT_OF_SYNC = "out_of_sync"    # last push failed, values differ
    ERROR = "error"


class EbayEnvironment(StrEnum):
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class SyncDirection(StrEnum):
    PUSH = "push"      # CompoLog -> eBay
    PULL = "pull"      # eBay -> CompoLog


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    DEAD = "dead"          # retry budget exhausted, needs a human


class AuditAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
