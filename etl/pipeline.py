"""
Reusable ETL pipeline: extract -> normalize -> clean -> merge -> load.
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from config import settings
from db.database import save_dataframe, load_dataframe
from etl.cleaner import clean_dataframe
from etl.merger import concat_datasets, merge_datasets
from etl.meta_ads import fetch_campaign_insights
from etl.normalizer import (
    coerce_numeric_columns,
    normalize_columns,
    standardize_date_column,
)

logger = logging.getLogger(__name__)


def extract_meta_ads(
    start_date: date | None = None,
    end_date: date | None = None,
) -> pd.DataFrame:
    """Extract and normalize Meta Ads data."""
    df = fetch_campaign_insights(start_date=start_date, end_date=end_date)
    if df.empty:
        return df
    df = normalize_columns(df)
    df = standardize_date_column(df)
    df = coerce_numeric_columns(df)
    return df


def normalize_report(df: pd.DataFrame, source_label: str = "report") -> pd.DataFrame:
    """Normalize an uploaded report DataFrame (Excel or Google Sheets)."""
    if df.empty:
        return df
    df = normalize_columns(df)
    df = standardize_date_column(df)
    df = coerce_numeric_columns(df)
    if "source" not in df.columns:
        df["source"] = source_label
    return df


def run_pipeline(
    report_dfs: list[pd.DataFrame] | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    persist: bool = True,
) -> pd.DataFrame:
    """
    Execute the full ETL pipeline.

    1. Extract Meta Ads data (if configured).
    2. Normalize each report DataFrame.
    3. Clean all DataFrames.
    4. Merge / concatenate into a unified dataset.
    5. Persist to the SQLite database.

    Parameters
    ----------
    report_dfs : list[pd.DataFrame], optional
        DataFrames from Google Sheets or Excel uploads.
    start_date, end_date : date, optional
        Date window for Meta Ads extraction.
    persist : bool
        Whether to save the result to the database.

    Returns
    -------
    pd.DataFrame – the unified, cleaned dataset.
    """
    all_sources: list[pd.DataFrame] = []

    # 1. Meta Ads
    meta_df = extract_meta_ads(start_date=start_date, end_date=end_date)
    if not meta_df.empty:
        meta_df = clean_dataframe(meta_df)
        all_sources.append(meta_df)
        logger.info("Meta Ads: %d rows", len(meta_df))

    # 2. Reports
    if report_dfs:
        for i, raw_df in enumerate(report_dfs):
            norm = normalize_report(raw_df, source_label=f"report_{i}")
            norm = clean_dataframe(norm)
            if not norm.empty:
                all_sources.append(norm)
                logger.info("Report %d: %d rows", i, len(norm))

    # 3. Merge
    if len(all_sources) == 0:
        logger.warning("No data sources available")
        return pd.DataFrame()
    elif len(all_sources) == 1:
        unified = all_sources[0]
    elif len(all_sources) == 2 and not meta_df.empty:
        unified = merge_datasets(all_sources[0], all_sources[1])
    else:
        unified = concat_datasets(all_sources)

    unified = clean_dataframe(unified)
    logger.info("Unified dataset: %d rows, %d columns", len(unified), len(unified.columns))

    # 4. Persist
    if persist:
        save_dataframe(unified, table_name="unified_analytics")
        logger.info("Saved unified data to database")

    return unified


def load_cached_data(table_name: str = "unified_analytics") -> pd.DataFrame:
    """Load the most recently persisted unified dataset."""
    return load_dataframe(table_name)
