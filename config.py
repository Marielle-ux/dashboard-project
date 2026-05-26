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


def _parse_account_ids() -> list[str]:
    """Parse comma-separated ad account IDs from env."""
    raw = _get_secret("META_AD_ACCOUNT_IDS")
    if not raw:
        single = _get_secret("META_AD_ACCOUNT_ID")
        return [single] if single else []
    return [aid.strip() for aid in raw.split(",") if aid.strip()]


@dataclass
class MetaAdsConfig:
    app_id: str = field(default_factory=lambda: _get_secret("META_APP_ID"))
    app_secret: str = field(default_factory=lambda: _get_secret("META_APP_SECRET"))
    access_token: str = field(default_factory=lambda: _get_secret("META_ACCESS_TOKEN"))
    ad_account_ids: list[str] = field(default_factory=_parse_account_ids)
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
    scopes: list[str] = field(
        default_factory=lambda: [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
    )

    @property
    def is_configured(self) -> bool:
        return Path(self.credentials_file).exists()


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
