"""
Meta (Facebook) Ads Manager API integration.
Fetches campaign-level metrics via the Marketing API.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import pandas as pd
import requests

from config import settings

logger = logging.getLogger(__name__)

API_BASE = "https://graph.facebook.com"

FIELDS = [
    "campaign_name",
    "adset_name",
    "ad_name",
    "spend",
    "impressions",
    "cpm",
    "cpc",
    "ctr",
    "clicks",
    "actions",
    "date_start",
    "date_stop",
]


def _build_url(endpoint: str) -> str:
    cfg = settings.meta_ads
    return f"{API_BASE}/{cfg.api_version}/{endpoint}"


def _default_params() -> dict:
    return {"access_token": settings.meta_ads.access_token}


def _parse_conversions(actions: list[dict] | None) -> int:
    """Extract total conversions from the actions breakdown."""
    if not actions:
        return 0
    conversion_types = {
        "offsite_conversion",
        "lead",
        "complete_registration",
        "purchase",
        "add_to_cart",
        "initiate_checkout",
    }
    total = 0
    for action in actions:
        action_type = action.get("action_type", "")
        if any(ct in action_type for ct in conversion_types):
            total += int(action.get("value", 0))
    return total


def fetch_campaign_insights(
    start_date: date | None = None,
    end_date: date | None = None,
    level: str = "campaign",
) -> pd.DataFrame:
    """
    Fetch ad insights from Meta Ads API.

    Parameters
    ----------
    start_date : date, optional
        Start of the reporting window (default: 30 days ago).
    end_date : date, optional
        End of the reporting window (default: today).
    level : str
        Aggregation level – 'campaign', 'adset', or 'ad'.

    Returns
    -------
    pd.DataFrame with columns:
        date, campaign_name, ad_set, spend, impressions,
        cpm, cpc, ctr, clicks, conversions, source
    """
    cfg = settings.meta_ads
    if not cfg.is_configured:
        logger.warning("Meta Ads API is not configured – returning empty DataFrame")
        return _empty_meta_df()

    if start_date is None:
        start_date = date.today() - timedelta(days=30)
    if end_date is None:
        end_date = date.today()

    account_id = cfg.ad_account_id
    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    url = _build_url(f"{account_id}/insights")
    params = {
        **_default_params(),
        "fields": ",".join(FIELDS),
        "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
        "level": level,
        "time_increment": 1,
        "limit": 500,
    }

    all_rows: list[dict] = []
    while url:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        all_rows.extend(payload.get("data", []))
        paging = payload.get("paging", {})
        url = paging.get("next")
        params = {}

    if not all_rows:
        logger.info("No data returned from Meta Ads API")
        return _empty_meta_df()

    df = pd.DataFrame(all_rows)
    return _transform_insights(df)


def _transform_insights(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize raw API response into a clean DataFrame."""
    result = pd.DataFrame()
    result["date"] = pd.to_datetime(df["date_start"]).dt.date
    result["campaign_name"] = df.get("campaign_name", "")
    result["ad_set"] = df.get("adset_name", "")
    result["spend"] = pd.to_numeric(df.get("spend", 0), errors="coerce").fillna(0)
    result["impressions"] = pd.to_numeric(
        df.get("impressions", 0), errors="coerce"
    ).fillna(0).astype(int)
    result["cpm"] = pd.to_numeric(df.get("cpm", 0), errors="coerce").fillna(0)
    result["cpc"] = pd.to_numeric(df.get("cpc", 0), errors="coerce").fillna(0)
    result["ctr"] = pd.to_numeric(df.get("ctr", 0), errors="coerce").fillna(0)
    result["clicks"] = pd.to_numeric(
        df.get("clicks", 0), errors="coerce"
    ).fillna(0).astype(int)
    result["conversions"] = df.get("actions", pd.Series([None] * len(df))).apply(
        _parse_conversions
    )
    result["source"] = "meta_ads"
    return result


def _empty_meta_df() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "date",
            "campaign_name",
            "ad_set",
            "spend",
            "impressions",
            "cpm",
            "cpc",
            "ctr",
            "clicks",
            "conversions",
            "source",
        ]
    )
