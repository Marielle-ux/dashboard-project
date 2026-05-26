"""
Centralized configuration for the analytics dashboard.
Reads credentials and settings from environment variables or .env file.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


@dataclass
class MetaAdsConfig:
    app_id: str = field(default_factory=lambda: os.getenv("META_APP_ID", ""))
    app_secret: str = field(default_factory=lambda: os.getenv("META_APP_SECRET", ""))
    access_token: str = field(default_factory=lambda: os.getenv("META_ACCESS_TOKEN", ""))
    ad_account_id: str = field(default_factory=lambda: os.getenv("META_AD_ACCOUNT_ID", ""))
    api_version: str = field(default_factory=lambda: os.getenv("META_API_VERSION", "v21.0"))

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_id)


@dataclass
class GoogleSheetsConfig:
    credentials_file: str = field(
        default_factory=lambda: os.getenv(
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
        default_factory=lambda: os.getenv(
            "DATABASE_PATH", str(BASE_DIR / "dashboard.db")
        )
    )


@dataclass
class AppConfig:
    meta_ads: MetaAdsConfig = field(default_factory=MetaAdsConfig)
    google_sheets: GoogleSheetsConfig = field(default_factory=GoogleSheetsConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    sync_interval_minutes: int = field(
        default_factory=lambda: int(os.getenv("SYNC_INTERVAL_MINUTES", "30"))
    )


settings = AppConfig()
