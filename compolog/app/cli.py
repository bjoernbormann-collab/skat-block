"""Command line helpers: `python -m app.cli <command>`.

Everything here is meant to be run by hand on the Mac mini. Keep it dependency
free (argparse, no click) so it works in a bare checkout.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import func, select

from app.db import session_scope
from app.logging_config import setup_logging
from app.models.auth import User
from app.models.automotive import AttributeDefinition
from app.models.catalog import ProductGroup
from app.models.ebay import ListingTemplate
from app.models.enums import SalesChannelType, UserRole
from app.models.inventory import StorageLocation
from app.models.orders import SalesChannel
from app.security import hash_password
from app.services.numbering import DEFAULT_RANGES, _ensure_range

# Attributes every connector article needs. Seeded so the Item-Specifics mapping
# in Modul 2 has a stable vocabulary from day one.
SEED_ATTRIBUTES: list[tuple[str, str, str, str]] = [
    # code, label_de, unit, ebay_aspect_name
    ("pin_count", "Polzahl", "", "Anzahl der Pins"),
    ("housing_type", "Bauform", "", "Bauform"),
    ("pitch", "Rastermaß", "mm", "Rastermaß"),
    ("colour", "Farbe", "", "Farbe"),
    ("contact_type", "Kontaktart", "", "Kontaktart"),
    ("sealing", "Dichtungsart", "", "Abdichtung"),
    ("temp_min", "Temperatur min.", "°C", ""),
    ("temp_max", "Temperatur max.", "°C", ""),
    ("current_rating", "Strombelastbarkeit", "A", "Strombelastbarkeit"),
    ("gender", "Ausführung", "", "Ausführung"),
]

DEFAULT_TEMPLATE_HTML = """<div style="font-family:Arial,Helvetica,sans-serif;max-width:900px">
  <h2>{{titel}}</h2>
  <p>{{kurzbeschreibung}}</p>
  {{langbeschreibung}}

  <h3>Technische Daten</h3>
  {{tech_attribute}}

  <h3>OE-Nummern</h3>
  <p>{{oe_nummern}}</p>

  <h3>Fahrzeugverwendung</h3>
  {{fitment_tabelle}}

  <p style="font-size:.85em;color:#666">
    OE-Nummern dienen ausschließlich Vergleichszwecken. Bitte gleichen Sie vor dem
    Kauf die Teilenummer mit Ihrem Fahrzeug ab.
  </p>
</div>"""


def cmd_create_user(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Passwort: ")
    if not args.password and password != getpass.getpass("Passwort wiederholen: "):
        print("Passwörter stimmen nicht überein.", file=sys.stderr)
        return 1
    if len(password) < 10:
        print("Passwort muss mindestens 10 Zeichen haben.", file=sys.stderr)
        return 1

    with session_scope() as db:
        if db.scalar(select(User).where(User.username == args.username)):
            print(f"Benutzer '{args.username}' existiert bereits.", file=sys.stderr)
            return 1
        db.add(User(
            username=args.username,
            full_name=args.full_name or args.username,
            role=args.role,
            password_hash=hash_password(password),
        ))
    print(f"Benutzer '{args.username}' angelegt (Rolle: {args.role}).")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Idempotent base data. Safe to run again after an upgrade."""
    created: list[str] = []
    with session_scope() as db:
        from datetime import date

        # Number ranges: create every counter row up front so they are visible
        # and editable in the UI before the first document is ever issued.
        from app.models.documents import NumberRange

        before = db.scalar(select(func.count()).select_from(NumberRange)) or 0
        for code in DEFAULT_RANGES:
            _ensure_range(db, code, date.today())  # noqa: DTZ011
        db.flush()
        after = db.scalar(select(func.count()).select_from(NumberRange)) or 0
        if after > before:
            created.append(f"{after - before} Nummernkreise")

        if not db.scalar(select(SalesChannel).where(SalesChannel.code == "ebay_de")):
            db.add(SalesChannel(
                code="ebay_de", name="eBay Deutschland",
                channel_type=SalesChannelType.EBAY.value,
                marketplace_id="EBAY_DE", is_sandbox=True,
            ))
            created.append("Verkaufskanal ebay_de (Sandbox)")

        if not db.scalar(select(StorageLocation).where(StorageLocation.code == "WE")):
            db.add(StorageLocation(code="WE", name="Wareneingang",
                                   pick_sequence=0, is_sellable=False))
            db.add(StorageLocation(code="RET", name="Retourenplatz",
                                   pick_sequence=0, is_sellable=False))
            created.append("Lagerorte WE / RET")

        existing_attrs = set(db.scalars(select(AttributeDefinition.code)).all())
        for order, (code, label, unit, aspect) in enumerate(SEED_ATTRIBUTES, start=1):
            if code in existing_attrs:
                continue
            db.add(AttributeDefinition(code=code, label_de=label, unit=unit,
                                       ebay_aspect_name=aspect, sort_order=order))
            created.append(f"Attribut {label}")

        if not db.scalar(select(ProductGroup).where(ProductGroup.code == "STV")):
            db.add(ProductGroup(code="STV", name="Steckverbinder"))
            created.append("Warengruppe STV")

        if not db.scalar(select(ListingTemplate).where(ListingTemplate.is_default.is_(True))):
            db.add(ListingTemplate(name="Standard", html=DEFAULT_TEMPLATE_HTML,
                                   is_default=True))
            created.append("Angebotsvorlage Standard")

    for item in created:
        print(f"  + {item}")
    print("Grunddaten angelegt." if created else "Nichts zu tun.")
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    from app.services.backup import run_backup

    artefacts = run_backup()
    for name, digest in artefacts.items():
        print(f"  {digest[:16]}…  {name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    parser = argparse.ArgumentParser(prog="compolog", description="CompoLog Verwaltung")
    sub = parser.add_subparsers(dest="command", required=True)

    p_user = sub.add_parser("create-user", help="Benutzer anlegen")
    p_user.add_argument("username")
    p_user.add_argument("--role", choices=[r.value for r in UserRole],
                        default=UserRole.ADMIN.value)
    p_user.add_argument("--full-name", default="")
    p_user.add_argument("--password", default=None,
                        help="Nur für Skripte – sonst wird interaktiv gefragt.")
    p_user.set_defaults(func=cmd_create_user)

    p_seed = sub.add_parser("seed", help="Grunddaten anlegen (idempotent)")
    p_seed.set_defaults(func=cmd_seed)

    p_backup = sub.add_parser("backup", help="Backup jetzt ausführen")
    p_backup.set_defaults(func=cmd_backup)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
