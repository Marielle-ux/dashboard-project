"""
Data cleaning utilities: missing-value handling and deduplication.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def drop_empty_rows(df: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    """
    Remove rows where the fraction of missing values exceeds *threshold*.
    """
    min_non_null = int(len(df.columns) * (1 - threshold))
    before = len(df)
    df = df.dropna(thresh=min_non_null)
    dropped = before - len(df)
    if dropped:
        logger.info("Dropped %d rows with >%.0f%% missing values", dropped, threshold * 100)
    return df


def fill_missing_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill NaN in standard metric columns with 0 (safe for sums/counts).
    """
    metric_cols = [
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
            df[col] = df[col].fillna(0)
    return df


def fill_missing_dimensions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fill NaN in dimension columns with 'Unknown'.
    """
    dim_cols = ["campaign_name", "ad_set", "source", "city"]
    for col in dim_cols:
        if col in df.columns:
            df[col] = df[col].fillna("Unknown")
    return df


def remove_duplicates(
    df: pd.DataFrame,
    subset: list[str] | None = None,
    keep: str = "last",
) -> pd.DataFrame:
    """
    Remove duplicate rows based on key columns.

    Parameters
    ----------
    subset : list[str], optional
        Columns to consider. Defaults to [date, campaign_name, ad_set, source].
    keep : str
        Which duplicate to keep ('first', 'last', or False).
    """
    if subset is None:
        subset = [c for c in ["date", "campaign_name", "ad_set", "source"] if c in df.columns]

    if not subset:
        return df

    before = len(df)
    df = df.drop_duplicates(subset=subset, keep=keep)
    dropped = before - len(df)
    if dropped:
        logger.info("Removed %d duplicate rows (key: %s)", dropped, subset)
    return df


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """
    Full cleaning pipeline: drop sparse rows, fill metrics, fill dims, dedup.
    """
    df = drop_empty_rows(df)
    df = fill_missing_metrics(df)
    df = fill_missing_dimensions(df)
    df = remove_duplicates(df)
    df = df.reset_index(drop=True)
    return df
