"""Jinja2 environment plus the German formatting filters used everywhere."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.config import settings

TEMPLATE_DIR = Path(__file__).parent / "templates"
BERLIN = ZoneInfo("Europe/Berlin")

templates = Jinja2Templates(directory=str(TEMPLATE_DIR))


def euro(value: Decimal | int | None, *, places: int = 2) -> str:
    """1234.5 -> '1.234,50 €'. Formats by hand: no locale dependency, and the
    Mac mini's locale settings are not something to rely on."""
    if value is None:
        return "–"
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    quantised = dec.quantize(Decimal(1).scaleb(-places))
    sign = "-" if quantised < 0 else ""
    digits = f"{abs(quantised):,.{places}f}"
    # en_US grouping -> de_DE grouping
    digits = digits.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return f"{sign}{digits} €"


def number_de(value: Decimal | int | float | None, places: int = 0) -> str:
    if value is None:
        return "–"
    text = f"{value:,.{places}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def datetime_de(value: datetime | None, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Render a stored UTC timestamp in Europe/Berlin."""
    if value is None:
        return "–"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(BERLIN).strftime(fmt)


def date_de(value: date | datetime | None) -> str:
    if value is None:
        return "–"
    if isinstance(value, datetime):
        return datetime_de(value, "%d.%m.%Y")
    return value.strftime("%d.%m.%Y")


def yesno(value: bool | None) -> str:
    return "Ja" if value else "Nein"


templates.env.filters["euro"] = euro
templates.env.filters["number_de"] = number_de
templates.env.filters["datetime_de"] = datetime_de
templates.env.filters["date_de"] = date_de
templates.env.filters["yesno"] = yesno
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["ebay_sandbox"] = settings.ebay_sandbox
templates.env.globals["environment"] = settings.environment
