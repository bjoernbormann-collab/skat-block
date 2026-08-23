"""Number ranges -- the gapless, transaction-safe counter (Modul 6)."""

from __future__ import annotations

from datetime import date

import pytest

from app.models.documents import NumberRange
from app.services.numbering import (
    UnknownNumberRangeError,
    format_number,
    next_number,
    peek_number,
)


def test_first_number_starts_at_one(db):
    assert next_number(db, "invoice", on=date(2026, 3, 5)) == "RE-2026-00001"


def test_numbers_are_consecutive_and_gapless(db):
    on = date(2026, 3, 5)
    numbers = [next_number(db, "invoice", on=on) for _ in range(25)]
    assert numbers == [f"RE-2026-{i:05d}" for i in range(1, 26)]
    assert len(set(numbers)) == 25, "eine Nummer wurde doppelt vergeben"


def test_yearly_reset_starts_a_new_range(db):
    assert next_number(db, "invoice", on=date(2026, 12, 31)) == "RE-2026-00001"
    assert next_number(db, "invoice", on=date(2027, 1, 1)) == "RE-2027-00001"
    # The old year keeps counting where it left off -- a late invoice for the
    # previous year must not restart the range.
    assert next_number(db, "invoice", on=date(2026, 12, 31)) == "RE-2026-00002"


def test_ranges_are_independent(db):
    on = date(2026, 3, 5)
    assert next_number(db, "invoice", on=on) == "RE-2026-00001"
    assert next_number(db, "credit_note", on=on) == "GS-2026-00001"
    assert next_number(db, "invoice", on=on) == "RE-2026-00002"


def test_continuous_range_ignores_the_year(db):
    """SKUs must stay unique for ever, so their range never resets."""
    first = next_number(db, "sku", on=date(2026, 6, 1))
    second = next_number(db, "sku", on=date(2027, 6, 1))
    assert first == "CL-001001"
    assert second == "CL-001002"


def test_rollback_consumes_no_number(db):
    """The whole point of allocating inside the caller's transaction."""
    on = date(2026, 3, 5)
    assert next_number(db, "invoice", on=on) == "RE-2026-00001"

    savepoint = db.begin_nested()
    assert next_number(db, "invoice", on=on) == "RE-2026-00002"
    savepoint.rollback()

    # 00002 was never committed, so it is handed out again -- no gap in the books.
    assert next_number(db, "invoice", on=on) == "RE-2026-00002"


def test_peek_does_not_consume(db):
    on = date(2026, 3, 5)
    assert peek_number(db, "invoice", on=on) == "RE-2026-00001"
    assert peek_number(db, "invoice", on=on) == "RE-2026-00001"
    assert next_number(db, "invoice", on=on) == "RE-2026-00001"


def test_unknown_range_raises(db):
    with pytest.raises(UnknownNumberRangeError):
        next_number(db, "gibt-es-nicht")


def test_user_edited_schema_is_respected(db):
    """An operator changing the schema in the UI must not be overwritten by the
    built-in default on the next call."""
    db.add(NumberRange(code="invoice", period="2026",
                       schema="R{yy}/{counter:04d}", yearly_reset=True,
                       current_value=41))
    db.flush()
    assert next_number(db, "invoice", on=date(2026, 3, 5)) == "R26/0042"


def test_invalid_schema_raises_instead_of_producing_junk():
    with pytest.raises(ValueError, match="ungültig"):
        format_number("RE-{unbekannt}-{counter}", 1, date(2026, 1, 1))
