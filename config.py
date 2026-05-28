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


def _get_secret(key: str, default: str = ""):
    """Read a config value with priority: st.secrets -> os.getenv -> default.

    May return a string, list, or dict depending on the TOML type used
    in Streamlit Cloud secrets.
    """
    # Priority 1: Streamlit Cloud secrets
    try:
        import streamlit as st
        val = st.secrets.get(key)
        if val is not None:
            return val
    except Exception:
        pass
    # Priority 2: environment variables (includes .env via load_dotenv)
    val = os.getenv(key)
    if val is not None and val != "":
        return val
    # Priority 3: default
    return default


def _parse_comma_list(key: str, fallback_key: str | None = None) -> list[str]:
    """Parse a list from env (comma-separated string) or st.secrets (TOML array).

    Safely handles None, empty strings, native lists, and comma-separated
    strings.  Falls back to *fallback_key* when the primary key is absent.
    """
    raw = _get_secret(key)

    # st.secrets returns native lists for TOML arrays
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]

    # Primary key missing or empty — try fallback
    if (raw is None or raw == "") and fallback_key:
        raw = _get_secret(fallback_key)
        if isinstance(raw, (list, tuple)):
            return [str(item).strip() for item in raw if str(item).strip()]
        if raw is None or raw == "":
            return []
        return [str(raw).strip()] if str(raw).strip() else []

    if raw is None or raw == "":
        return []

    return [item.strip() for item in str(raw).split(",") if item.strip()]


@dataclass
class MetaAdsConfig:
    app_id: str = field(default_factory=lambda: str(_get_secret("META_APP_ID") or ""))
    app_secret: str = field(default_factory=lambda: str(_get_secret("META_APP_SECRET") or ""))
    access_token: str = field(default_factory=lambda: str(_get_secret("META_ACCESS_TOKEN") or ""))
    ad_account_ids: list[str] = field(
        default_factory=lambda: _parse_comma_list("META_AD_ACCOUNT_IDS", "META_AD_ACCOUNT_ID")
    )
    api_version: str = field(default_factory=lambda: str(_get_secret("META_API_VERSION", "v21.0") or "v21.0"))

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
    header_row: int = field(
        default_factory=lambda: int(str(_get_secret("GOOGLE_HEADER_ROW", "3")))
    )
    scopes: list[str] = field(
        default_factory=lambda: [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
    )

    @property
    def is_configured(self) -> bool:
        """True if credentials are available (file or st.secrets)."""
        if Path(self.credentials_file).exists():
            return True
        # Check st.secrets for cloud deployment
        try:
            import streamlit as st
            return "google_credentials" in st.secrets
        except Exception:
            return False

    @property
    def credentials_info(self) -> dict | None:
        """Return credentials as a dict (from file or st.secrets)."""
        import json
        # Prefer local file
        if Path(self.credentials_file).exists():
            try:
                with open(self.credentials_file) as f:
                    return json.load(f)
            except Exception:
                return None
        # Fall back to st.secrets
        try:
            import streamlit as st
            if "google_credentials" in st.secrets:
                return dict(st.secrets["google_credentials"])
        except Exception:
            pass
        return None

    @property
    def service_account_email(self) -> str:
        """Return the service account email from credentials."""
        info = self.credentials_info
        return info.get("client_email", "") if info else ""


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
        default_factory=lambda: int(str(_get_secret("SYNC_INTERVAL_MINUTES", "15")))
    )


settings = AppConfig()
