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
    # Google Sheets hospitality columns
    "выручка_день": "revenue_day",
    "выручка_основная": "revenue_main",
    "выручка_ночь": "revenue_night",
    "кол_во_чеков_кабинки": "cabin_checks",
    "кол_во_гостей_кабинки": "cabin_guests",
    "выручка_кабинки": "cabin_revenue",
    "предзаказ": "preorder",
    "_от_общей_суммы": "pct_total",
    "утро": "morning_revenue",
    "вечер": "evening_revenue",
    "ночь": "night_revenue",
    "кол_во_чеков_общий_зал": "hall_checks",
    "кол_во_гостей_общий_зал": "hall_guests",
    "выручка_общий_зал": "hall_revenue",
    "дневная_с_1000_до_1800": "guests_day",
    "основная_с_1800_до_0000": "guests_evening",
    "ночная_с_0000_до_0500": "guests_night",
    "др": "event_birthday",
    "девичник": "event_bachelorette",
    "тдр": "event_tdr",
    "гендерпати": "event_gender_party",
    "гап": "event_gap",
    "автепати": "event_auto_party",
    "официанты": "waiters",
    "отдел_бронирования": "booking_dept",
    "спец_предложения": "special_offers",
    "кабинки": "cabins",
    "как_узнали_о_нас": "lead_source",
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


def _clean_numeric_string(series: pd.Series) -> pd.Series:
    """Strip non-breaking spaces, regular spaces used as thousand separators,
    and replace comma decimal separators before numeric coercion."""
    cleaned = series.astype(str)
    # Remove non-breaking spaces (\xa0) and regular spaces used as grouping
    cleaned = cleaned.str.replace("\xa0", "", regex=False)
    cleaned = cleaned.str.replace(" ", "", regex=False)
    # Remove percentage signs
    cleaned = cleaned.str.replace("%", "", regex=False)
    # Replace comma decimal separator with dot
    cleaned = cleaned.str.replace(",", ".", regex=False)
    return cleaned


def coerce_numeric_columns(
    df: pd.DataFrame,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """
    Convert specified columns to numeric types, coercing errors to NaN.
    If *columns* is None, attempts to convert all standard metric columns.
    Handles non-breaking spaces, comma decimals, and percentage signs.
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
        "revenue_day",
        "revenue_main",
        "revenue_night",
        "cabin_checks",
        "cabin_guests",
        "cabin_revenue",
        "preorder",
        "pct_total",
        "morning_revenue",
        "evening_revenue",
        "night_revenue",
        "hall_checks",
        "hall_guests",
        "hall_revenue",
        "guests_day",
        "guests_evening",
        "guests_night",
    ]
    for col in metric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(
                _clean_numeric_string(df[col]), errors="coerce"
            )
    return df
