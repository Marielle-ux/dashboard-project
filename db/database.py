"""
SQLite database operations for the analytics dashboard.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager

import pandas as pd

from config import settings

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    """Context manager for SQLite connections."""
    conn = sqlite3.connect(settings.database.path)
    try:
        yield conn
    finally:
        conn.close()


def save_dataframe(
    df: pd.DataFrame,
    table_name: str,
    if_exists: str = "replace",
) -> None:
    """Save a DataFrame to the SQLite database."""
    with get_connection() as conn:
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)
        logger.info(
            "Saved %d rows to table '%s'", len(df), table_name
        )


def load_dataframe(table_name: str) -> pd.DataFrame:
    """Load a table from the SQLite database into a DataFrame."""
    with get_connection() as conn:
        try:
            df = pd.read_sql(f"SELECT * FROM {table_name}", conn)
            return df
        except Exception:
            logger.warning("Table '%s' not found in database", table_name)
            return pd.DataFrame()


def list_tables() -> list[str]:
    """List all tables in the database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return [row[0] for row in cursor.fetchall()]


def get_table_info(table_name: str) -> pd.DataFrame:
    """Return column info for a given table."""
    with get_connection() as conn:
        return pd.read_sql(f"PRAGMA table_info({table_name})", conn)


UNIFIED_SCHEMA = """
-- Recommended schema for the unified analytics table.
-- This is created automatically by pandas to_sql, but documented here
-- for reference and for direct SQL migrations.

CREATE TABLE IF NOT EXISTS unified_analytics (
    date            TEXT,
    campaign_name   TEXT,
    ad_set          TEXT,
    source          TEXT,
    city            TEXT,
    spend           REAL    DEFAULT 0,
    impressions     INTEGER DEFAULT 0,
    cpm             REAL    DEFAULT 0,
    cpc             REAL    DEFAULT 0,
    ctr             REAL    DEFAULT 0,
    clicks          INTEGER DEFAULT 0,
    conversions     INTEGER DEFAULT 0,
    revenue         REAL    DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_unified_date ON unified_analytics(date);
CREATE INDEX IF NOT EXISTS idx_unified_campaign ON unified_analytics(campaign_name);
CREATE INDEX IF NOT EXISTS idx_unified_source ON unified_analytics(source);
"""
