"""
Data merging logic: combine Meta Ads data with Google Sheets / Excel reports
into a single unified DataFrame.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

MERGE_KEYS = ["date", "campaign_name", "ad_set", "source"]


def merge_datasets(
    meta_df: pd.DataFrame,
    report_df: pd.DataFrame,
    how: str = "outer",
) -> pd.DataFrame:
    """
    Merge Meta Ads data with an uploaded/Google Sheets report.

    The merge is performed on the intersection of MERGE_KEYS that exist
    in both DataFrames.  An outer join is used by default so that no rows
    are lost.

    Parameters
    ----------
    meta_df : pd.DataFrame
        Cleaned Meta Ads data.
    report_df : pd.DataFrame
        Cleaned report data (Google Sheets or Excel).
    how : str
        Join type passed to ``pd.merge``.

    Returns
    -------
    pd.DataFrame – merged result.
    """
    if meta_df.empty and report_df.empty:
        return pd.DataFrame()
    if meta_df.empty:
        return report_df.copy()
    if report_df.empty:
        return meta_df.copy()

    available_keys = [k for k in MERGE_KEYS if k in meta_df.columns and k in report_df.columns]

    if not available_keys:
        logger.warning(
            "No common merge keys found between datasets – concatenating instead"
        )
        return pd.concat([meta_df, report_df], ignore_index=True)

    logger.info("Merging on keys: %s (how=%s)", available_keys, how)
    merged = pd.merge(
        meta_df,
        report_df,
        on=available_keys,
        how=how,
        suffixes=("_meta", "_report"),
    )
    return merged


def concat_datasets(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """
    Stack multiple DataFrames vertically (union-style).
    Useful when merging is not appropriate (e.g., different granularity).
    """
    non_empty = [df for df in dfs if not df.empty]
    if not non_empty:
        return pd.DataFrame()
    combined = pd.concat(non_empty, ignore_index=True)
    logger.info("Concatenated %d datasets -> %d total rows", len(non_empty), len(combined))
    return combined
