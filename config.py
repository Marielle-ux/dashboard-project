"""
Centralized configuration for the analytics dashboard.
Reads credentials and settings from environment variables, .env file,
or Streamlit Cloud secrets (st.secrets).
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _get_secret(key: str, default: str = "") -> str:
    """Read a config value from env vars first, then st.secrets fallback."""
    val = os.getenv(key)
    if val:
        return val
    try:
        import streamlit as st
        return st.secrets.get(key, default)
    except Exception:
        return default


def _parse_comma_list(key: str, fallback_key: str = "") -> list[str]:
    """Parse a comma-separated list from env."""
    raw = _get_secret(key)
    if not raw and fallback_key:
        single = _get_secret(fallback_key)
        return [single] if single else []
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass
class MetaAdsConfig:
    app_id: str = field(default_factory=lambda: _get_secret("META_APP_ID"))
    app_secret: str = field(default_factory=lambda: _get_secret("META_APP_SECRET"))
    access_token: str = field(default_factory=lambda: _get_secret("META_ACCESS_TOKEN"))
    ad_account_ids: list[str] = field(
        default_factory=lambda: _parse_comma_list("META_AD_ACCOUNT_IDS", "META_AD_ACCOUNT_ID")
    )
    api_version: str = field(default_factory=lambda: _get_secret("META_API_VERSION", "v21.0"))

    @property
    def ad_account_id(self) -> str:
        """Backward-compatible: return first account ID."""
        return self.ad_account_ids[0] if self.ad_account_ids else ""

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_ids)


@dataclass
class GoogleSheetsConfig:
    credentials_file: str = field(
        default_factory=lambda: _get_secret(
            "GOOGLE_CREDENTIALS_FILE",
            str(BASE_DIR / "google_credentials.json"),
        )
    )
    spreadsheet_names: list[str] = field(
        default_factory=lambda: _parse_comma_list("GOOGLE_SPREADSHEET_NAMES")
    )
    scopes: list[str] = field(
        default_factory=lambda: [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
    )

    @property
    def is_configured(self) -> bool:
        return Path(self.credentials_file).exists()

    @property
    def service_account_email(self) -> str:
        """Return the service account email from the credentials file."""
        import json
        try:
            with open(self.credentials_file) as f:
                data = json.load(f)
            return data.get("client_email", "")
        except Exception:
            return ""


@dataclass
class DatabaseConfig:
    path: str = field(
        default_factory=lambda: _get_secret(
            "DATABASE_PATH", str(BASE_DIR / "dashboard.db")
        )
    )


@dataclass
class AppConfig:
    meta_ads: MetaAdsConfig = field(default_factory=MetaAdsConfig)
    google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    sync_interval_minutes: int = field(
        default_factory=lambda: int(_get_secret("SYNC_INTERVAL_MINUTES", "30"))
    )


settings = AppConfig()
