"""All ORM models.

Importing this package registers every mapper with Base.metadata, which is what
Alembic's autogenerate needs. Keep the import list complete -- a model that is not
imported here silently disappears from the migrations.
"""

from app.models.accounting import (
    AccountingExport,
    FeeRule,
    OrderFee,
    TaxRate,
)
from app.models.audit import AuditLog
from app.models.auth import LoginSession, User
from app.models.automotive import (
    ArticleAttribute,
    ArticleFitment,
    ArticleOeNumber,
    AttributeDefinition,
    CrossReference,
    OeNumber,
    Vehicle,
)
from app.models.base import Base
from app.models.catalog import (
    Article,
    ArticleImage,
    Manufacturer,
    ProductGroup,
    Supplier,
)
from app.models.documents import Document, DocumentLine, NumberRange
from app.models.ebay import (
    EbayApiCall,
    EbayCategoryMapping,
    EbayCredential,
    EbayListing,
    EbayRateLimit,
    ListingTemplate,
    SyncTask,
)
from app.models.inventory import (
    PurchaseOrder,
    PurchaseOrderLine,
    StockLevel,
    StockMovement,
    StockReservation,
    Stocktake,
    StocktakeLine,
    StorageLocation,
)
from app.models.orders import (
    Address,
    Order,
    OrderChannelReference,
    OrderLine,
    ReturnLine,
    ReturnRequest,
    SalesChannel,
)
from app.models.picking import PickLine, PickList, PickListOrder
from app.models.shipping import Carrier, Shipment, ShipmentLine, ShippingProduct

__all__ = [
    "AccountingExport",
    "Address",
    "Article",
    "ArticleAttribute",
    "ArticleFitment",
    "ArticleImage",
    "ArticleOeNumber",
    "AttributeDefinition",
    "AuditLog",
    "Base",
    "Carrier",
    "CrossReference",
    "Document",
    "DocumentLine",
    "EbayApiCall",
    "EbayCategoryMapping",
    "EbayCredential",
    "EbayListing",
    "EbayRateLimit",
    "FeeRule",
    "ListingTemplate",
    "LoginSession",
    "Manufacturer",
    "NumberRange",
    "OeNumber",
    "Order",
    "OrderChannelReference",
    "OrderFee",
    "OrderLine",
    "PickLine",
    "PickList",
    "PickListOrder",
    "ProductGroup",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "ReturnLine",
    "ReturnRequest",
    "SalesChannel",
    "Shipment",
    "ShipmentLine",
    "ShippingProduct",
    "StockLevel",
    "StockMovement",
    "StockReservation",
    "Stocktake",
    "StocktakeLine",
    "StorageLocation",
    "Supplier",
    "SyncTask",
    "TaxRate",
    "User",
    "Vehicle",
]
