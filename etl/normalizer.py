"""
Column name normalization and data type standardization.
Handles inconsistent naming across Meta Ads, Google Sheets, and Excel sources.
"""

from __future__ import annotations

import re

import pandas as pd

# Mapping of common raw column names (lowercased) to canonical names.
# Extend this dictionary as you encounter new naming variations.
COLUMN_ALIASES: dict[str, str] = {
    # Date
    "date": "date",
    "day": "date",
    "дата": "date",
    "report_date": "date",
    "date_start": "date",
    "date_stop": "date",
    "reporting_starts": "date",
    # Campaign
    "campaign": "campaign_name",
    "campaign_name": "campaign_name",
    "campaign name": "campaign_name",
    "кампания": "campaign_name",
    "название кампании": "campaign_name",
    # Ad set
    "ad_set": "ad_set",
    "adset": "ad_set",
    "adset_name": "ad_set",
    "ad set": "ad_set",
    "ad set name": "ad_set",
    "группа объявлений": "ad_set",
    # Source / platform
    "source": "source",
    "platform": "source",
    "источник": "source",
    "канал": "source",
    # Spend
    "spend": "spend",
    "cost": "spend",
    "amount_spent": "spend",
    "amount spent": "spend",
    "расход": "spend",
    "затраты": "spend",
    "бюджет": "spend",
    # Impressions
    "impressions": "impressions",
    "imps": "impressions",
    "показы": "impressions",
    # CPM
    "cpm": "cpm",
    "cost_per_1000_impressions": "cpm",
    # CPC
    "cpc": "cpc",
    "cost_per_click": "cpc",
    "cost per click": "cpc",
    # CTR
    "ctr": "ctr",
    "click_through_rate": "ctr",
    "click-through rate": "ctr",
    # Clicks
    "clicks": "clicks",
    "link_clicks": "clicks",
    "клики": "clicks",
    "переходы": "clicks",
    # Conversions
    "conversions": "conversions",
    "results": "conversions",
    "конверсии": "conversions",
    "лиды": "conversions",
    # City
    "city": "city",
    "город": "city",
    "region": "city",
    "регион": "city",
    # Revenue
    "revenue": "revenue",
    "выручка": "revenue",
    "итого": "revenue",
    "total": "revenue",
}


def clean_column_name(name: str) -> str:
    """
    Clean a single column name:
    - strip whitespace
    - lowercase
    - replace spaces/dashes with underscores
    - remove non-alphanumeric chars (except underscores and Cyrillic)
    """
    name = str(name).strip().lower()
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"[^\w]", "", name, flags=re.UNICODE)
    return name


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize column names of a DataFrame using the alias map.
    Unknown columns are kept with cleaned names.
    Columns that resolve to empty strings or start with 'unnamed' are dropped.
    """
    new_columns = {}
    for col in df.columns:
        cleaned = clean_column_name(col)
        canonical = COLUMN_ALIASES.get(cleaned, cleaned)
        new_columns[col] = canonical

    df = df.rename(columns=new_columns)

    # Drop columns with empty names or generic 'unnamed_*' names
    cols_to_drop = [
        c for c in df.columns
        if not c or c.startswith("unnamed")
    ]
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)

    # Deduplicate column names by appending a suffix
    seen: dict[str, int] = {}
    final_cols: list[str] = []
    for col in df.columns:
        if col in seen:
            seen[col] += 1
            final_cols.append(f"{col}_{seen[col]}")
        else:
            seen[col] = 0
            final_cols.append(col)
    df.columns = pd.Index(final_cols)

    return df


def standardize_date_column(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    """
    Parse and standardize a date column to ``datetime64[ns]``.
    Tries multiple date formats commonly seen in the data.
    """
    if col not in df.columns:
        return df

    df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
    return df


def coerce_numeric_columns(
    df: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Convert specified columns to numeric types, coercing errors to NaN.
    If *columns* is None, attempts to convert all standard metric columns.
    """
    metric_cols = columns or [
        "spend",
        "impressions",
        "cpm",
        "cpc",
        "ctr",
        "clicks",
        "conversions",
        "revenue",
    ]
    for col in metric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
