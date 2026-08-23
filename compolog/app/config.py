"""Central application settings.

Everything configurable lives here and is fed from the environment / .env file.
Nothing in the code base may hard-code a path, credential or business constant --
if you find yourself wanting to, add it to this class instead.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repository root (…/compolog). Used to resolve relative data paths.
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------------------------------------------------------- general
    app_name: str = "CompoLog"
    environment: Literal["development", "production"] = "development"
    debug: bool = False
    # Secret for signing the session cookie. MUST be overridden in production.
    secret_key: str = "change-me-in-dotenv-please"
    session_cookie_name: str = "compolog_session"
    session_max_age_seconds: int = 60 * 60 * 12
    # Set to True once the app is served over HTTPS (Cloudflare Tunnel does this).
    session_cookie_secure: bool = False
    # Hosts allowed to reach the app. "*" is fine on a LAN-only Mac mini, but should
    # be narrowed to the tunnel hostname once it is publicly reachable.
    trusted_hosts: list[str] = Field(default_factory=lambda: ["*"])

    # --------------------------------------------------------------- database
    # SQLite today, PostgreSQL later -- the models and migrations are written so
    # that only this URL has to change.
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'compolog.db'}"
    database_echo: bool = False

    # ------------------------------------------------------------- data paths
    data_dir: Path = BASE_DIR / "data"
    image_dir: Path = BASE_DIR / "data" / "images"
    document_dir: Path = BASE_DIR / "data" / "documents"
    backup_dir: Path = BASE_DIR / "data" / "backups"
    log_dir: Path = BASE_DIR / "data" / "logs"

    # ---------------------------------------------------------------- logging
    log_level: str = "INFO"
    log_json: bool = True
    log_rotate_mb: int = 20
    log_backup_count: int = 10

    # ------------------------------------------------------------ number ranges
    # Default schema for the internal SKU. Placeholders: {counter}, {year}, {month},
    # {group} (Warengruppen-Kurzzeichen). Zero padding via Python format spec.
    sku_schema: str = "CL-{counter:06d}"
    sku_start: int = 1000

    # ------------------------------------------------------------------ company
    # Used on every document -- §14 UStG mandatory fields.
    company_name: str = "Bitte in .env setzen"
    company_street: str = ""
    company_zip: str = ""
    company_city: str = ""
    company_country: str = "DE"
    company_vat_id: str = ""          # USt-IdNr., e.g. DE123456789
    company_tax_number: str = ""      # Steuernummer (alternative to USt-IdNr.)
    company_email: str = ""
    company_phone: str = ""
    company_bank_name: str = ""
    company_iban: str = ""
    company_bic: str = ""
    company_register: str = ""        # Handelsregister / Registergericht
    company_managing_director: str = ""
    # Kleinunternehmer nach §19 UStG -> invoices are issued without VAT and must
    # carry the corresponding note. Changes the whole tax handling, so it lives here.
    small_business_scheme: bool = False
    default_vat_rate: Decimal = Decimal("19.00")

    # --------------------------------------------------------------------- eBay
    ebay_sandbox: bool = True
    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_redirect_uri: str = ""       # RuName / redirect URI configured at eBay
    ebay_marketplace_id: str = "EBAY_DE"
    ebay_sync_interval_minutes: int = 15
    # What happens when internal stock hits zero: keep the offer at quantity 0 or
    # end it entirely.
    ebay_zero_stock_action: Literal["set_zero", "end_offer"] = "set_zero"

    # --------------------------------------------------------------------- DHL
    dhl_sandbox: bool = True
    dhl_api_key: str = ""
    dhl_username: str = ""
    dhl_password: str = ""
    dhl_billing_number: str = ""

    # ----------------------------------------------------------- background jobs
    # Turned off in tests and in one-shot CLI commands so no scheduler thread
    # starts behind the caller's back.
    scheduler_enabled: bool = True

    # ---------------------------------------------------------------- backups
    backup_enabled: bool = True
    backup_cron_hour: int = 3
    backup_keep_days: int = 30

    @field_validator("trusted_hosts", mode="before")
    @classmethod
    def _split_hosts(cls, value: object) -> object:
        """Allow TRUSTED_HOSTS=a.example,b.example in the .env file."""
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def ensure_directories(self) -> None:
        """Create the data directories on start-up so nothing fails later on."""
        for path in (self.data_dir, self.image_dir, self.document_dir,
                     self.backup_dir, self.log_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
