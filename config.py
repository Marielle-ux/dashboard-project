"""
Centralized configuration for the analytics dashboard.
Reads credentials and settings from environment variables, .env file,
or Streamlit Cloud secrets (st.secrets).

Designed to never crash the app when secrets are missing: every access
to ``st.secrets`` is wrapped in a try/except so the dashboard can boot
on a fresh Streamlit Cloud deployment and surface a clear status in
the UI instead of raising.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")


def _safe_st_secrets() -> Any:
    """Return ``st.secrets`` if available, else ``None``.

    Accessing ``st.secrets`` raises when no ``secrets.toml`` file exists
    (e.g. local dev without secrets configured). We swallow that here so
    callers can treat the result as "no secrets available".
    """
    try:
        import streamlit as st  # local import: keep config import-safe
        # Touch a method to force any lazy-load errors to surface here.
        _ = st.secrets  # type: ignore[attr-defined]
        return st.secrets  # type: ignore[attr-defined]
    except Exception:
        return None


def _get_secret(key: str, default: str = "") -> Any:
    """Read a config value with priority: st.secrets -> os.getenv -> default.

    Returns the native TOML type from ``st.secrets`` (str, list, dict, int…)
    or a string from the environment. Never raises.
    """
    secrets = _safe_st_secrets()
    if secrets is not None:
        try:
            if key in secrets:
                val = secrets[key]
                if val is not None and val != "":
                    return val
        except Exception:
            # Defensive: never let a malformed secrets file break startup.
            pass

    val = os.getenv(key)
    if val is not None and val != "":
        return val
    return default


def _get_first_secret(keys: list[str], default: str = "") -> Any:
    """Return the first non-empty secret found across *keys* (in order).

    Useful when a single config value is exposed under multiple names
    (e.g. ``META_APP_SECRET`` and the legacy ``ads_manager_secret``).
    """
    for k in keys:
        val = _get_secret(k)
        if val is not None and val != "":
            return val
    return default


def _secret_contains(key: str) -> bool:
    """Return True if ``key`` is present (and non-empty) in st.secrets."""
    secrets = _safe_st_secrets()
    if secrets is None:
        return False
    try:
        if key not in secrets:
            return False
        val = secrets[key]
        return val is not None and val != ""
    except Exception:
        return False


def _parse_list(key: str, fallback_key: str | None = None) -> list[str]:
    """Parse a list from env (comma-separated) or st.secrets (TOML array).

    Safely handles None, empty strings, native lists, and comma-separated
    strings. Falls back to *fallback_key* when the primary key is absent.
    """
    raw = _get_secret(key)

    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]

    if (raw is None or raw == "") and fallback_key:
        raw = _get_secret(fallback_key)
        if isinstance(raw, (list, tuple)):
            return [str(item).strip() for item in raw if str(item).strip()]

    if raw is None or raw == "":
        return []

    return [item.strip() for item in str(raw).split(",") if item.strip()]


# Backward-compatible alias (older imports may still use this name).
_parse_comma_list = _parse_list


@dataclass
class MetaAdsConfig:
    app_id: str = field(default_factory=lambda: str(_get_secret("META_APP_ID") or ""))
    app_secret: str = field(
        default_factory=lambda: str(
            _get_first_secret(["META_APP_SECRET", "ads_manager_secret"]) or ""
        )
    )
    access_token: str = field(default_factory=lambda: str(_get_secret("META_ACCESS_TOKEN") or ""))
    ad_account_ids: list[str] = field(
        default_factory=lambda: _parse_list("META_AD_ACCOUNT_IDS", "META_AD_ACCOUNT_ID")
    )
    api_version: str = field(default_factory=lambda: str(_get_secret("META_API_VERSION", "v21.0") or "v21.0"))

    @property
    def ad_account_id(self) -> str:
        """Backward-compatible: return first account ID."""
        return self.ad_account_ids[0] if self.ad_account_ids else ""

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_ids)

    def status(self) -> dict[str, bool]:
        """Non-sensitive True/False snapshot for the debug panel."""
        return {
            "META_ACCESS_TOKEN": bool(self.access_token),
            "META_AD_ACCOUNT_IDS": bool(self.ad_account_ids),
            "META_APP_SECRET": bool(self.app_secret),
            "META_APP_ID": bool(self.app_id),
            "configured": self.is_configured,
        }


@dataclass
class GoogleSheetsConfig:
    credentials_file: str = field(
        default_factory=lambda: str(
            _get_secret(
                "GOOGLE_CREDENTIALS_FILE",
                str(BASE_DIR / "google_credentials.json"),
            )
        )
    )
    spreadsheet_names: list[str] = field(
        default_factory=lambda: _parse_list("GOOGLE_SPREADSHEET_NAMES")
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

    # ------------------------------------------------------------------
    # Credential discovery
    # ------------------------------------------------------------------
    @property
    def credentials_info(self) -> dict | None:
        """Return service-account credentials as a dict.

        Resolution order:
        1. Local JSON file at ``credentials_file``
        2. ``GOOGLE_CREDENTIALS_JSON`` in st.secrets / env (JSON string)
        3. ``[google_credentials]`` TOML table in st.secrets
        """
        # 1) Local file
        if self.credentials_file and Path(self.credentials_file).exists():
            try:
                with open(self.credentials_file) as f:
                    return json.load(f)
            except Exception as exc:
                logger.warning("Could not parse %s: %s", self.credentials_file, exc)

        # 2) GOOGLE_CREDENTIALS_JSON as a JSON string
        raw = _get_secret("GOOGLE_CREDENTIALS_JSON")
        if isinstance(raw, dict):
            return dict(raw)
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning("GOOGLE_CREDENTIALS_JSON is not valid JSON: %s", exc)

        # 3) [google_credentials] TOML table
        secrets = _safe_st_secrets()
        if secrets is not None:
            try:
                if "google_credentials" in secrets:
                    return dict(secrets["google_credentials"])
            except Exception:
                pass

        return None

    @property
    def is_configured(self) -> bool:
        """True if credentials are discoverable (file, JSON string, or table)."""
        if self.credentials_file and Path(self.credentials_file).exists():
            return True
        if _secret_contains("GOOGLE_CREDENTIALS_JSON") or os.getenv("GOOGLE_CREDENTIALS_JSON"):
            return True
        secrets = _safe_st_secrets()
        if secrets is not None:
            try:
                if "google_credentials" in secrets:
                    return True
            except Exception:
                pass
        return False

    @property
    def service_account_email(self) -> str:
        """Return the service account email from credentials (or empty)."""
        info = self.credentials_info
        return info.get("client_email", "") if info else ""

    def status(self) -> dict[str, bool]:
        """Non-sensitive True/False snapshot for the debug panel."""
        info = self.credentials_info
        return {
            "GOOGLE_CREDENTIALS_JSON": bool(
                _secret_contains("GOOGLE_CREDENTIALS_JSON")
                or os.getenv("GOOGLE_CREDENTIALS_JSON")
            ),
            "google_credentials_table": self._has_credentials_table(),
            "credentials_file_present": bool(
                self.credentials_file and Path(self.credentials_file).exists()
            ),
            "credentials_parsed": bool(info),
            "GOOGLE_SPREADSHEET_NAMES": bool(self.spreadsheet_names),
            "configured": self.is_configured,
        }

    @staticmethod
    def _has_credentials_table() -> bool:
        secrets = _safe_st_secrets()
        if secrets is None:
            return False
        try:
            return "google_credentials" in secrets
        except Exception:
            return False


@dataclass
class DatabaseConfig:
    path: str = field(
        default_factory=lambda: str(
            _get_secret("DATABASE_PATH", str(BASE_DIR / "dashboard.db"))
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

    def status(self) -> dict[str, dict[str, bool]]:
        """Aggregate True/False status for the debug panel.

        Never returns the actual secret values — only booleans.
        """
        return {
            "meta": self.meta_ads.status(),
            "google_sheets": self.google_sheets.status(),
            "secrets_file_available": _safe_st_secrets() is not None,
        }


settings = AppConfig()
