"""Gapless, transaction-safe number ranges (Modul 6, used from Modul 1 onwards).

WHY THIS FILE IS FUSSY
----------------------
GoBD requires invoice numbers to be complete and unique: no gaps, no duplicates.
Two naive implementations both fail:

* ``SELECT max(number)+1`` -- two concurrent writers read the same maximum and
  produce the same number.
* Allocating the number in its own short transaction ("get a number, commit, then
  write the invoice") -- if the invoice write then fails, the number is burnt and
  a gap appears in the books.

What works is a counter row that is incremented by an atomic UPDATE *inside the
caller's transaction*, and the document written in that same transaction:

    with session_scope() as db:                 # one transaction
        number = next_number(db, "invoice")     # takes a row lock
        db.add(Document(number=number, ...))    # same transaction
    # commit -- number and document appear together, or neither does

The UPDATE holds a row lock (PostgreSQL) or the database write lock (SQLite)
until COMMIT, so a second writer blocks rather than duplicating. On rollback the
counter rolls back with everything else, so no number is consumed.

THE PRICE
---------
This serialises document creation. That is a deliberate trade: at a few dozen
documents a day the lock is held for milliseconds, and a gapless range is worth
far more than the throughput. Do not "optimise" this by pre-allocating numbers.

WHAT THIS CANNOT PROTECT AGAINST
--------------------------------
A number allocated and committed for a document that is later deleted still
leaves a gap. That is why finalised documents are never deleted -- corrections go
through a cancellation document (see app/models/documents.py).
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.documents import NumberRange

# Ranges created on first use if they do not exist yet.
# schema placeholders: {counter}, {year}, {month}, {yy}
DEFAULT_RANGES: dict[str, dict] = {
    "invoice": {
        "schema": "RE-{year}-{counter:05d}",
        "yearly_reset": True,
        "description": "Rechnungen",
    },
    "credit_note": {
        "schema": "GS-{year}-{counter:05d}",
        "yearly_reset": True,
        "description": "Gutschriften",
    },
    "cancellation": {
        "schema": "ST-{year}-{counter:05d}",
        "yearly_reset": True,
        "description": "Stornorechnungen",
    },
    "delivery_note": {
        "schema": "LS-{year}-{counter:05d}",
        "yearly_reset": True,
        "description": "Lieferscheine",
    },
    "order": {
        "schema": "AU-{year}-{counter:05d}",
        "yearly_reset": True,
        "description": "Interne Auftragsnummern",
    },
    "purchase_order": {
        "schema": "BE-{year}-{counter:04d}",
        "yearly_reset": True,
        "description": "Lieferantenbestellungen",
    },
    "return": {
        "schema": "RM-{year}-{counter:04d}",
        "yearly_reset": True,
        "description": "Retouren",
    },
    "pick_list": {
        "schema": "PL-{year}{month}-{counter:04d}",
        "yearly_reset": True,
        "description": "Kommissionieraufträge",
    },
    "sku": {
        # Continuous, never reset -- an SKU must stay unique for ever.
        "schema": settings.sku_schema,
        "yearly_reset": False,
        "description": "Artikelnummern",
        "start": settings.sku_start,
    },
}


class UnknownNumberRangeError(LookupError):
    """Raised for a range code that has no definition and no database row."""


def _period_for(code: str, on: date, yearly_reset: bool) -> str:
    return str(on.year) if yearly_reset else ""


def _ensure_range(db: Session, code: str, on: date) -> NumberRange:
    """Fetch the counter row, creating it from DEFAULT_RANGES on first use."""
    definition = DEFAULT_RANGES.get(code)
    yearly_reset = bool(definition["yearly_reset"]) if definition else False

    # An existing row wins over the default -- the user may have changed the
    # schema in the UI, and re-reading the default would silently revert it.
    existing_any = db.scalar(select(NumberRange).where(NumberRange.code == code))
    if existing_any is not None:
        yearly_reset = existing_any.yearly_reset

    period = _period_for(code, on, yearly_reset)
    row = db.scalar(
        select(NumberRange).where(NumberRange.code == code, NumberRange.period == period)
    )
    if row is not None:
        return row

    if existing_any is None and definition is None:
        raise UnknownNumberRangeError(
            f"Kein Nummernkreis '{code}' definiert. In DEFAULT_RANGES ergänzen "
            "oder in der Oberfläche anlegen."
        )

    template = existing_any if existing_any is not None else None
    row = NumberRange(
        code=code,
        period=period,
        schema=template.schema if template else definition["schema"],
        yearly_reset=yearly_reset,
        current_value=(definition or {}).get("start", 0) if template is None else 0,
        description=template.description if template else definition.get("description", ""),
    )
    db.add(row)
    db.flush()
    return row


def next_number(db: Session, code: str, *, on: date | None = None) -> str:
    """Allocate the next number of the range ``code``.

    MUST be called inside the transaction that also writes the record the number
    belongs to. See the module docstring.
    """
    # Local calendar date on purpose: an invoice issued at 01:30 CET belongs
    # to that German business day, not to the previous UTC one.
    on = on or date.today()  # noqa: DTZ011
    row = _ensure_range(db, code, on)

    # Atomic increment. Expressed as an UPDATE on the column rather than
    # row.current_value += 1 in Python, so the database -- not this process --
    # decides the new value, and a concurrent writer blocks on the row lock.
    db.execute(
        update(NumberRange)
        .where(NumberRange.id == row.id)
        .values(current_value=NumberRange.current_value + 1)
    )
    # Re-read inside the same transaction: we see our own increment, and anyone
    # else is still waiting for our COMMIT.
    db.expire(row, ["current_value"])
    counter = db.scalar(
        select(NumberRange.current_value).where(NumberRange.id == row.id)
    )
    assert counter is not None  # the row was just updated

    return format_number(row.schema, counter, on)


def format_number(schema: str, counter: int, on: date) -> str:
    """Render a counter through a range schema.

    Unknown placeholders raise instead of producing a half-formatted number --
    a malformed invoice number is worse than a loud failure.
    """
    try:
        return schema.format(
            counter=counter,
            year=on.year,
            yy=f"{on.year % 100:02d}",
            month=f"{on.month:02d}",
            day=f"{on.day:02d}",
        )
    except (KeyError, IndexError, ValueError) as exc:
        raise ValueError(
            f"Nummernkreis-Schema '{schema}' ist ungültig: {exc}"
        ) from exc


def peek_number(db: Session, code: str, *, on: date | None = None) -> str:
    """The number that ``next_number`` would hand out. Preview only -- never
    persist this; it is not reserved."""
    # Local calendar date on purpose: an invoice issued at 01:30 CET belongs
    # to that German business day, not to the previous UTC one.
    on = on or date.today()  # noqa: DTZ011
    row = _ensure_range(db, code, on)
    return format_number(row.schema, row.current_value + 1, on)
